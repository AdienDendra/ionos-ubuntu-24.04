from google import genai
import os
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print(f"{'MODEL NAME':<45} | {'INPUT':<10} | {'OUTPUT':<10} | {'ACTIONS'}")
print("-" * 90)

'''
cara run:
python3 cek_genai_version.py
'''

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


