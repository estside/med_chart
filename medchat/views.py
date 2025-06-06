import os
from django.conf import settings
from django.shortcuts import render
from .forms import ChatForm
from .voice import transcribe_with_groq
from .brain import encode_image, analyze_image_with_query
from .voice_of_doctor import text_to_speech_with_gtts
from django.core.files.storage import default_storage
from django.http import HttpResponse
from reportlab.pdfgen import canvas
from io import BytesIO
# views.py
import os
from io import BytesIO
from django.conf import settings
from django.http import HttpResponse
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from io import BytesIO
from datetime import datetime
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.csrf import ensure_csrf_cookie

@ensure_csrf_cookie


@csrf_protect

def download_chat_pdf(request):
    chat_history = request.session.get("chat_history", [])

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ChatStyle", fontSize=12, leading=16, spaceAfter=10))

    story = []
    story.append(Paragraph("🩺 AI Doctor Full Chat", styles["Title"]))

    for msg in chat_history:
        role = "You" if msg["role"] == "user" else "Doctor"
        content = msg["content"].strip().replace("\n", "<br/>")
        formatted_text = f"<b>{role}:</b> {content}"
        story.append(Paragraph(formatted_text, styles["ChatStyle"]))
        story.append(Spacer(1, 6))

    doc.build(story)
    buffer.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    filename = f"chat_transcript_{timestamp}.pdf"

    return HttpResponse(
        buffer,
        content_type="application/pdf",
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


# Ensure the media folder exists
os.makedirs(settings.MEDIA_ROOT, exist_ok=True)

# System prompt
system_prompt = """
You are a professional medical doctor. You answer patient queries based on medical reasoning. Be concise, accurate, and do not speculate. When unsure, recommend seeing a real doctor.
Here are some examples:
User: I have had a sore throat for 2 days.
Doctor: It could be a mild viral infection. Gargle with warm salt water and monitor your temperature. If symptoms persist for more than 3 days, see a physician.

User: My child has a rash and fever.
Doctor: This may indicate an allergic reaction or an infection such as measles. Please consult a pediatrician.

Now answer the following:
"""

def doctor_chat_view(request):
    response_text = ""
    audio_response = ""

    # ✅ Clear chat on fresh load or ?clear=true
    if request.method == "GET":
        if request.GET.get("clear") == "true" or "chat_history" not in request.session:
            request.session["chat_history"] = [
                {"role": "assistant", "content": "👨‍⚕️ Hello! Please ask your question."}
            ]

    if request.method == "POST":
        form = ChatForm(request.POST, request.FILES)
        if form.is_valid():
            text_input = form.cleaned_data.get("text_input")
            audio_file = form.cleaned_data.get("audio_input")
            image_file = form.cleaned_data.get("image_input")

            # Transcribe audio if present
            user_query = text_input
            if audio_file:
                audio_path = default_storage.save(audio_file.name, audio_file)
                user_query = transcribe_with_groq(
                    GROQ_API_KEY=os.getenv("GROQ_API_KEY"),
                    audio_filepath=os.path.join(settings.MEDIA_ROOT, audio_path),
                    stt_model="whisper-large-v3"
                )

            # Fetch conversation history
            messages = request.session.get("chat_history", [])

            # Add user message
            messages.append({"role": "user", "content": user_query})

            # Process with or without image
            if image_file:
                image_path = default_storage.save(image_file.name, image_file)
                image_full_path = os.path.join(settings.MEDIA_ROOT, image_path)
                encoded_img = encode_image(image_full_path)
                query_text = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in messages])
                response_text = analyze_image_with_query(query_text, "meta-llama/llama-4-scout-17b-16e-instruct", encoded_img)
            else:
                from groq import Groq
                client = Groq(api_key=os.getenv("GROQ_API_KEY"))
                chat = client.chat.completions.create(
                    model="meta-llama/llama-4-scout-17b-16e-instruct",
                    messages=[{"role": "system", "content": system_prompt}] + messages
                )
                response_text = chat.choices[0].message.content

            # Add assistant reply + follow-up
            messages.append({"role": "assistant", "content": response_text})
            messages.append({"role": "assistant", "content": "🩺 Do you have a follow-up question?"})

            # Save conversation
            request.session["chat_history"] = messages

            # Convert to speech
            output_audio_path = os.path.join(settings.MEDIA_ROOT, "doctor_response.mp3")
            text_to_speech_with_gtts(response_text, output_audio_path)
            audio_response = "doctor_response.mp3"
    else:
        
        form = ChatForm()

    return render(request, "medchat/chat.html", {
    "form": form,
    "response_text": response_text,
    "audio_response": audio_response,
    "show_typing": bool(response_text)  # ✅ Typing indicator control
})
