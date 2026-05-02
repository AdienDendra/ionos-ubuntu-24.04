from google import genai
import os
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print(f"{'MODEL NAME':<45} | {'INPUT':<10} | {'OUTPUT':<10} | {'ACTIONS'}")
print("-" * 90)

for m in client.models.list():
    # Ambil limit I/O, kasih default 'N/A' kalau properti nggak ada
    input_limit = getattr(m, 'input_token_limit', 'N/A')
    output_limit = getattr(m, 'output_token_limit', 'N/A')
    
    # Ambil rate_limits jika ada (biasanya di API terbaru dikelompokkan)
    rate_info = ""
    if hasattr(m, 'rate_limits') and m.rate_limits:
        rate_info = f" | Limits: {m.rate_limits}"
    
    # Tampilkan hanya yang bisa generate content biar nggak kepanjangan
    if 'generateContent' in m.supported_actions:
        print(f"{m.name:<45} | {input_limit:<10} | {output_limit:<10} | {m.supported_actions}{rate_info}")



# # Ambil detail model spesifik
# model_info = client.models.get(model="gemini-3-flash-preview")


"""from google import genai

# Initialize the client
# It will automatically look for GOOGLE_API_KEY in your environment variables
client = genai.Client(api_key="YOUR_API_KEY")

# Generate content
response = client.models.generate_content(
    model="gemini-2.0-flash", 
    contents="Explain AI in one sentence."
)

print(response.text)"""


"""# Panggil Gemini 3 Flash Preview
response = client.models.generate_content(
    model="gemini-3-flash-preview", 
    contents="Analisa cuaca mancing di Sydney besok..."
)

print(response.text)"""