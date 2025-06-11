import os
from io import BytesIO
from datetime import datetime
from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.core.files.storage import default_storage
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

from .forms import ChatForm
from .voice import transcribe_with_groq
from .brain import encode_image, analyze_image_with_query
from .voice_of_doctor import text_to_speech_with_gtts
from django.http import StreamingHttpResponse


# Ensure the media folder exists
os.makedirs(settings.MEDIA_ROOT, exist_ok=True)

# System prompt for the doctor
system_prompt = """
You are a professional medical doctor. You answer patient queries based on medical reasoning. Be concise, accurate, and do not speculate. When unsure, recommend seeing a real doctor.
"""

# Generate medical summary from chat history
def summarize_chat(chat_history):
    doctor_responses = "\n".join(
        msg["content"] for msg in chat_history if msg["role"] == "assistant" and not msg["content"].startswith("🩺")
    )

    from groq import Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    summary_prompt = f"""
You are a helpful medical assistant. Summarize the following conversation between a doctor and a patient into a clear, summary including observed symptoms, suggested causes, tests, and treatment (if mentioned). Do not include any follow-up or chit-chat. Be medically factual and concise.

Conversation:
{doctor_responses}

Final summary:
"""

    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{"role": "system", "content": summary_prompt}]
    )
    return response.choices[0].message.content.strip()

# Helper function to save and get media URL
def save_media_file(file, prefix=""):
    """Save uploaded file and return its URL"""
    if not file:
        return None
    
    # Generate unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}_{file.name}"
    
    # Save file
    file_path = default_storage.save(filename, file)
    
    # Return URL
    return f"{settings.MEDIA_URL}{file_path}"

# Chat view
@ensure_csrf_cookie
@csrf_protect
def doctor_chat_view(request):
    response_text = ""
    audio_response = ""

    # Initialize session variables
    if "voice_enabled" not in request.session:
        request.session["voice_enabled"] = True  # default: voice on

    if request.method == "GET":
        if request.GET.get("clear") == "true" or "chat_history" not in request.session:
            request.session["chat_history"] = [
                {"role": "assistant", "content": "👨‍⚕️ Hello! Please ask your question."}
            ]
        if "voice" in request.GET:
            request.session["voice_enabled"] = (request.GET.get("voice") == "true")

    if request.method == "POST":
        form = ChatForm(request.POST, request.FILES)
        if form.is_valid():
            text_input = form.cleaned_data.get("text_input")
            audio_file = form.cleaned_data.get("audio_input")
            image_file = form.cleaned_data.get("image_input")

            # Handle media files
            image_url = None
            audio_url = None
            
            if image_file:
                image_url = save_media_file(image_file, "image")
            
            if audio_file:
                audio_url = save_media_file(audio_file, "audio")

            # Transcribe audio if provided
            user_query = text_input or ""
            if audio_file:
                audio_path = default_storage.save(audio_file.name, audio_file)
                transcribed_text = transcribe_with_groq(
                    GROQ_API_KEY=os.getenv("GROQ_API_KEY"),
                    audio_filepath=os.path.join(settings.MEDIA_ROOT, audio_path),
                    stt_model="whisper-large-v3"
                )
                user_query = f"{user_query} {transcribed_text}".strip()

            # Prepare user message
            user_message = {
                "role": "user", 
                "content": user_query or "Sent an attachment"
            }
            
            # Add media URLs if present
            if image_url:
                user_message["image_url"] = image_url
            if audio_url:
                user_message["audio_url"] = audio_url

            # Get chat history and add user message
            messages = request.session.get("chat_history", [])
            messages.append(user_message)

            # Process the query
            if image_file:
                image_path = default_storage.save(image_file.name, image_file)
                encoded_img = encode_image(os.path.join(settings.MEDIA_ROOT, image_path))
                query_text = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in messages])
                response_text = analyze_image_with_query(query_text, "meta-llama/llama-4-scout-17b-16e-instruct", encoded_img)
            else:
                from groq import Groq
                client = Groq(api_key=os.getenv("GROQ_API_KEY"))
                
                # Prepare messages for API (exclude media URLs)
                api_messages = []
                for msg in messages:
                    api_msg = {"role": msg["role"], "content": msg["content"]}
                    api_messages.append(api_msg)
                
                chat = client.chat.completions.create(
                    model="meta-llama/llama-4-scout-17b-16e-instruct",
                    messages=[{"role": "system", "content": system_prompt}] + api_messages
                )
                response_text = chat.choices[0].message.content

            # Add assistant response
            messages.append({"role": "assistant", "content": response_text})
            messages.append({"role": "assistant", "content": "🩺 Do you have a follow-up question?"})
            request.session["chat_history"] = messages

            # Generate summary
            summary = summarize_chat(messages)
            request.session["chat_summary"] = summary

            # Generate voice response if enabled
            if request.session.get("voice_enabled", True):
                output_audio_path = os.path.join(settings.MEDIA_ROOT, "doctor_response.mp3")
                text_to_speech_with_gtts(response_text, output_audio_path)
                audio_response = "doctor_response.mp3"

    else:
        form = ChatForm()

    return render(request, "medchat/chat.html", {
        "form": form,
        "response_text": response_text,
        "audio_response": audio_response,
        "show_typing": bool(response_text),
        "final_summary": request.session.get("chat_summary", ""),
        "voice_enabled": request.session.get("voice_enabled", True)
    })

# PDF: Full chat with summary
def download_chat_pdf(request):
    chat_history = request.session.get("chat_history", [])
    summary = request.session.get("chat_summary", "")

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ChatStyle", fontSize=12, leading=16, spaceAfter=10))

    story = []
    if summary:
        story.append(Paragraph("🩺 AI Doctor Final Summary", styles["Title"]))
        story.append(Spacer(1, 12))
        story.append(Paragraph(summary, styles["Normal"]))
        story.append(Spacer(1, 24))

    story.append(Paragraph("🩺 AI Doctor Full Chat", styles["Title"]))

    for msg in chat_history:
        role = "You" if msg["role"] == "user" else "Doctor"
        content = msg["content"].strip().replace("\n", "<br/>")
        
        # Add media indicators
        media_info = ""
        if msg.get("image_url"):
            media_info += " [Image attached]"
        if msg.get("audio_url"):
            media_info += " [Audio attached]"
            
        formatted_text = f"<b>{role}:</b> {content}{media_info}"
        story.append(Paragraph(formatted_text, styles["ChatStyle"]))
        story.append(Spacer(1, 6))

    doc.build(story)
    buffer.seek(0)

    filename = f"full_chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return HttpResponse(buffer, content_type="application/pdf", headers={'Content-Disposition': f'attachment; filename="{filename}"'})

# PDF: Only the summary
def download_summary_pdf(request):
    summary = request.session.get("chat_summary", "No summary generated yet.")
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch)
    styles = getSampleStyleSheet()
    story = [Paragraph("🩺 AI Doctor Summary Only", styles["Title"]), Spacer(1, 12), Paragraph(summary, styles["Normal"])]
    doc.build(story)
    buffer.seek(0)

    filename = f"summary_only_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return HttpResponse(buffer, content_type="application/pdf", headers={'Content-Disposition': f'attachment; filename="{filename}"'})