import os
import json
import aiohttp
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from fpdf import FPDF
import nest_asyncio
import asyncio
import re
import time
from dotenv import load_dotenv
from collections import defaultdict

nest_asyncio.apply()

load_dotenv()

GROQ_API_KEY = os.getenv('GROQ_API_KEY')
TOKEN = os.getenv('TELEGRAM_TOKEN')

if not GROQ_API_KEY or not TOKEN:
    raise ValueError("API keys are missing! Please set GROQ_API_KEY and TELEGRAM_TOKEN as environment variables.")

url = "https://api.groq.com/openai/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {GROQ_API_KEY}"
}

# Dictionary to store the timestamps of messages for each user
user_message_timestamps = defaultdict(list)

# Define rate limit parameters
MAX_MESSAGES = 5  # Max number of messages allowed within the time window
TIME_WINDOW = 30  # Time window in seconds (e.g., 30 seconds)

# Function to handle the /start command
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "Hello! I can help you generate detailed exam questions from your syllabus.\n\n"
        "To get started, simply send me your syllabus in text format. For example:\n\n"
        "1. Chapter 1: Introduction to Python\n"
        "   - Variables and Data Types\n"
        "   - Control Structures\n\n"
        "2. Chapter 2: Object-Oriented Programming\n"
        "   - Classes and Objects\n"
        "   - Inheritance\n\n"
        "Once you send me the syllabus, I'll create exam questions based on key topics, active recall, and real-world applications, and send you a PDF with the questions.\n\n"
        "Feel free to send a syllabus now, and I'll get started!\n\n"
        "For any suggestions or feedback, feel free to reach out to me on LinkedIn linkedin.com/in/thesupersaurabh."
    )

# Function to handle the syllabus in text format with rate limiting
async def handle_text(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id

    # Get the current time
    current_time = time.time()

    # Get the list of timestamps for the user's previous messages
    user_messages = user_message_timestamps[user_id]

    # Remove messages that are outside the time window
    user_messages = [timestamp for timestamp in user_messages if current_time - timestamp < TIME_WINDOW]
    
    # Add the current message timestamp
    user_messages.append(current_time)

    # Update the user's message timestamps
    user_message_timestamps[user_id] = user_messages

    # Check if the user has exceeded the message limit
    if len(user_messages) > MAX_MESSAGES:
        await update.message.reply_text("You are sending messages too quickly. Please wait a moment before sending more.")
        return

    # Check if the received message is a text message
    if not update.message.text:
        await update.message.reply_text("Please send a valid syllabus in text format.")
        return

    syllabus_text = update.message.text

    # Validate syllabus length
    if len(syllabus_text) > 4000:  
        await update.message.reply_text("Your syllabus is too long. Please send a shorter version or split it into multiple parts.")
        return

    # Send processing message to the user
    await update.message.reply_text("Processing your syllabus, please wait...")

    # New prompt asking for detailed questions for each topic in the syllabus
    syllabus_prompt = f"""
    Hey, look at this syllabus and give me detailed exam questions for **every topic** mentioned in the syllabus. Follow these guidelines to make the questions more effective:
    1. **80/20 Rule (Pareto Principle)**: Focus on the key concepts that cover the most important 80% of the material. Prioritize the topics that are central to the subject and likely to appear frequently in exams.
    2. **Active Recall**: Include questions that push the student to actively recall and retrieve information from memory. For example:
        - "What is the definition of...?"
        - "How would you apply [concept] in practice?"
        - "What are the key differences between [concept A] and [concept B]?"
    3. **Spaced Repetition**: Introduce questions of varying complexity. Include simple recall questions initially, followed by more complex application and analysis-based questions. Consider revisiting core concepts in different ways to reinforce learning over time.
    4. **Practical/Real-World Applications**: Where applicable, include questions that ask how the concepts in the syllabus can be applied in real-world scenarios. For example:
        - "How would a professional in this field use [concept] in practice?"
        - "Give a real-life example of [concept] and explain its significance."
    5. **Concept Mapping**: Where possible, generate questions that encourage the student to link related concepts. For example:
        - "How does [Topic A] relate to [Topic B]?"
        - "Explain how [concept] can be applied in [specific scenario]."
    6. **Interdisciplinary Connections**: If applicable, generate questions that connect this subject with others, encouraging the student to see the broader picture. For example:
        - "How does [subject 1] relate to [subject 2]?"
        - "What are the intersections between [concept from syllabus] and [concept from another discipline]?"

    **Note:** Please ensure that the questions are clear, concise, and relevant to the syllabus topics. The more detailed and varied the questions, the better the preparation for the exam.

    The syllabus is as follows:
    {syllabus_text}
    """

    # Prepare the data for the API request
    data = {
        "model": "llama3-8b-8192",  # Use your preferred model
        "messages": [{"role": "user", "content": syllabus_prompt}]
    }

    # Make the API request asynchronously
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 200:
                    response_data = await response.json()
                    assistant_message = response_data.get('choices', [{}])[0].get('message', {}).get('content', "")

                    if not assistant_message:
                        await update.message.reply_text("Sorry, no questions were generated.")
                        return

                    # Generate PDF with the assistant's response
                    pdf_file_path = await generate_pdf(assistant_message, user_id)

                    # Send the PDF back to the user
                    with open(pdf_file_path, 'rb') as pdf_file:
                        await update.message.reply_document(document=InputFile(pdf_file, filename="exam_questions.pdf"))

                    # Clean up the generated PDF file
                    os.remove(pdf_file_path)
                else:
                    print(f"Failed request: {response.status}, {await response.text()}")
                    await update.message.reply_text("Sorry, there was an error processing your syllabus.")
        except Exception as e:
            print(f"Error processing syllabus (Text): {e}") 
            await update.message.reply_text("An error occurred while processing your request. Please try again later.")

# Function to generate a PDF from the assistant's response
async def generate_pdf(assistant_message: str, user_id: int) -> str:
    timestamp = int(time.time())
    pdf_file_path = f"exam_questions_{user_id}_{timestamp}.pdf"
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", style='B', size=14)
    pdf.cell(200, 10, txt="Generated Exam Questions", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", style='I', size=12)
    pdf.cell(0, 10, txt="Questions created using ", ln=True)
    bot_link = "https://t.me/SyllabusXpertPro_bot"
    pdf.set_text_color(0, 0, 255)
    pdf.link(10, pdf.get_y(), 180, 10, bot_link)
    pdf.cell(0, 10, txt=bot_link, ln=True)
    pdf.ln(10)
    pdf.set_font("Arial", size=12)

    lines = assistant_message.split("\n")
    for line in lines:
        if '**' in line:
            parts = re.split(r'(\*\*.*?\*\*)', line)
            for part in parts:
                if part.startswith("**") and part.endswith("**"):
                    pdf.set_font("Arial", style='B', size=12)
                    pdf.multi_cell(0, 10, txt=part[2:-2])  # Remove '**'
                else:
                    pdf.set_font("Arial", size=12)
                    pdf.multi_cell(0, 10, txt=part)
        elif line.startswith("# "):
            pdf.set_font("Arial", style='B', size=12)
            pdf.multi_cell(0, 10, txt=line[2:])
            pdf.ln(2)
            pdf.set_font("Arial", size=12)
        elif line.startswith("- "):
            pdf.multi_cell(0, 10, txt=f"• {line[2:]}")
        else:
            pdf.multi_cell(0, 10, txt=line)

    pdf.output(pdf_file_path)
    return pdf_file_path

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    # Command handler to start the bot
    application.add_handler(CommandHandler("start", start))

    # Message handler to process only text messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Run the bot
    application.run_polling()

if __name__ == "__main__":
    main()
