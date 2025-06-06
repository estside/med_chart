import gradio as gr
from brain import encode_image, analyze_image_with_query
from voice import transcribe_with_groq
from voice_of_doctor import text_to_speech_with_gtts

GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # Load via env if needed

# Initial system prompt
system_prompt = """
You are a professional medical doctor. You answer patient queries based on medical reasoning. Be concise, accurate, and do not speculate. When unsure, recommend seeing a real doctor.Answer should be short.

Here are some examples:
User: I have had a sore throat for 2 days.
Doctor: It could be a mild viral infection. Gargle with warm salt water and monitor your temperature. If symptoms persist for more than 3 days, see a physician.

User: My child has a rash and fever.
Doctor: This may indicate an allergic reaction or an infection such as measles. Please consult a pediatrician.

Now answer the following:
"""

def chat_with_doctor(text_input, audio_input, image_input, history):
    messages = history or []

    # Step 1: Get user input
    if text_input:
        user_query = text_input
    elif audio_input:
        user_query = transcribe_with_groq(
            GROQ_API_KEY="your-api-key",
            audio_filepath=audio_input,
            stt_model="whisper-large-v3"
        )
    else:
        user_query = "No input provided."

    messages.append({"role": "user", "content": user_query})

    # Step 2: Prepare input for LLM
    if image_input:
        prompt = format_chat_history(messages)
        encoded_img = encode_image(image_input)
        response_text = analyze_image_with_query(
            query=prompt,
            encoded_image=encoded_img,
            model="meta-llama/llama-4-scout-17b-16e-instruct"
        )
    else:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        chat = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role": "system", "content": system_prompt}] + messages
        )
        response_text = chat.choices[0].message.content

    messages.append({"role": "assistant", "content": response_text})

    # Step 3: Convert to audio
    output_mp3 = "final.mp3"
    text_to_speech_with_gtts(input_text=response_text, output_filepath=output_mp3)

    return response_text, output_mp3, messages

def combine_conversation(messages):
    return "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in messages])
def format_chat_history(messages):
    return "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in messages])


iface = gr.Interface(
    fn=chat_with_doctor,
    inputs=[
        gr.Textbox(label="Type your question (optional)", lines=2),
        gr.Audio(sources=["microphone"], type="filepath", label="Or speak your question"),
        gr.Image(type="filepath", label="Optional Medical Image"),
        gr.State([])  # Stores conversation history
    ],
    outputs=[
        gr.Textbox(label="Doctor's Reply"),
        gr.Audio(label="Doctor's Voice"),
        gr.State()  # Return updated history
    ],
    title="Advanced AI Doctor"
)
iface.launch(debug=True)