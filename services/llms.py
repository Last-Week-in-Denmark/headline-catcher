
from xmlrpc import client

def process_with_ai(text, task_type, target_lang):
    """
    Passes text to OpenAI GPT-4o-mini with specific system instructions.
    
    Input:
      - text (str): The raw summary or scraped full body text.
      - task_type (str): "translate_only" or "deep_analyze".
      - target_lang (str): User's selected output language.
    Output: (str) - AI generated text.
    """
    if task_type == "translate_only":
        system_instruction = f"You are a professional translator. Translate the following text into {target_lang}. Do not summarize, just translate accurately."
    else: 
        system_instruction = f"You are an expert news editor. Analyze the article text. Provide a highly engaging headline, followed by a 3-bullet point summary of the key facts. Write the entire response in {target_lang}."

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": text}
            ],
            temperature=0.3 # Low temperature for factual consistency
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"**AI Error:** {e}"