import os
import re

from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from dateutil import parser
from google import genai
from geopy.geocoders import Nominatim
from dotenv import load_dotenv

from config import LUNAR_ANCHOR
from ai_analisis import generate_analisis_cuaca, generate_analisis_spesies
from data_cuaca import get_astronomy_data, get_coordinates_data, get_weather_data


# Load file .env secara otomatis
load_dotenv()

NAMA_HARI = {
    "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
    "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"
}

NAMA_BULAN = {
    "January": "Januari", "February": "Februari", "March": "Maret", "April": "April",
    "May": "Mei", "June": "Juni", "July": "Juli", "August": "Agustus",
    "September": "September", "October": "Oktober", "November": "November", "December": "Desember"
}

LUNAR_ANCHOR = datetime(*LUNAR_ANCHOR)

app = Flask(__name__)

# Setup Gemini
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("❌ Kunci Gemini tidak ditemukan di file .env!")
client = genai.Client(api_key=API_KEY)

# Setup  Geocoder
geolocator = Nominatim(user_agent="bot_mancing_sydney_pro_adien")


def buat_laporan(lat, lon, lokasi, target_dt, jam_mulai, jam_selesai):
    try:
        # 1. AMBIL DATA (Sudah include dynamic ocean discovery)
        marine, weather, tide_data, f_lat, f_lon = get_weather_data(lat, lon)     

        if not weather or 'hourly' not in weather:
            return f"❌ Maaf Om, data cuaca untuk {lokasi} tidak bisa diakses saat ini."

        # 2. CARI INDEX TANGGAL SECARA DINAMIS (Anti-Hardcode Timezone)
        target_date_str = target_dt.strftime("%Y-%m-%d")
        all_times = weather['hourly']['time']
        start_idx = next((i for i, t in enumerate(all_times) if t.startswith(target_date_str)), -1)

        if start_idx == -1:
            return f"❌ Data untuk tanggal {target_date_str} belum tersedia, Om."

        # 3. FLAG DATA MARINE
        marine_is_missing = 'hourly' not in marine or not marine['hourly'].get('wave_height')

        # 4. FORMAT TANGGAL & ASTRONOMI
        hari_id = NAMA_HARI.get(target_dt.strftime("%A"))
        bulan_id = NAMA_BULAN.get(target_dt.strftime("%B"))
        tgl_str = f"{hari_id}, {target_dt.strftime('%d')} {bulan_id} {target_dt.year}"
        
        astro = get_astronomy_data(target_dt, lat, lon)
        
        # 5. SUSUN HEADER
        header = (
            f"*LAPORAN CUACA UTK MANCING DI {lokasi.upper()}*\n"
            f"📅 {tgl_str}\n"
            f"🌅 Sunrise: {astro['sr']} | 🌇 Sunset: {astro['ss']}\n\n"
            f"*FISH ACTIVITY:*\n"
            f"{astro['low']}\n{astro['minor']}\n{astro['major']}\n"
            f"\n"
            f"{'-'*30}\n"
        )

        # 6. LOOPING DATA PER JAM
        data_points = ""
        count = 0
        for i in range(24):
            idx = start_idx + i
            if idx >= len(all_times): break
            
            waktu_lokal = parser.isoparse(all_times[idx])
            jam = waktu_lokal.hour

            if jam_mulai <= jam <= jam_selesai:
                # Weather Data
                wind = weather['hourly']['wind_speed_10m'][idx]
                temp = weather['hourly']['temperature_2m'][idx]
                pres = weather['hourly']['surface_pressure'][idx]
                prec_prob = weather['hourly']['precipitation_probability'][idx]
                prec = weather['hourly']['precipitation'][idx]

                # Marine Data (Dinamis N/A)
                if not marine_is_missing and idx < len(marine['hourly']['wave_height']):
                    wv = f"{marine['hourly']['wave_height'][idx]:.2f}"
                    sw = f"{marine['hourly']['swell_wave_height'][idx]:.2f}"
                    swp = f"{marine['hourly']['swell_wave_period'][idx]:.1f}"
                else:
                    wv = sw = swp = "N/A"

                # --- DATA TIDE (Pasang Surut) ---
                if tide_data and idx < len(tide_data):
                    current_t = tide_data[idx]
                    # Logika Tren: Bandingkan dengan jam sebelumnya
                    prev_t = tide_data[idx-1] if idx > 0 else current_t
                    
                    if current_t > prev_t:
                        tren = "📈" # Naik (Flow)
                    elif current_t < prev_t:
                        tren = "📉" # Surut (Ebb)
                    else:
                        tren = "↔️" # Flat (Slack)
                    
                    # Format 2 desimal seperti request Om
                    tide_val = f"{current_t:.2f}m {tren}"
                else:
                    tide_val = "N/A"

                # Rain Icon Logic
                if prec_prob == 0: rain_status = "☀️"
                elif prec_prob <= 30: rain_status = "🌤️"
                elif prec_prob <= 70: rain_status = "🌦️"
                else: rain_status = "⛈️" if prec > 5 else "🌧️"

                data_points += (
                    f"Jam *{jam:02d}:00*\n"
                    f"🌬️ Wind: {wind} km/h | {rain_status} {prec}mm ({prec_prob}%)\n"
                    f"🌊 Wave: {wv}m | Swell: {sw}m | Tide: {tide_val}\n"
                    f"⏱️ Per: {swp}s | 🌡️ {temp}°C | ⏲️ {pres}hPa\n"
                    f"{'-'*30}\n"
                )
                count += 1

        if count == 0:
            return f"❌ Jam mancing di {lokasi} sudah lewat. Coba ketik: `/cek {lokasi} besok`"

        # 7. FOOTER & AI ANALYSIS
        #footer_info = f"📍 Sensor: `{f_lat}, {f_lon}`\n🏠 Req: `{lat}, {lon}`\n"
        
        # Panggil fungsi AI yang baru
        analisa_teks, model_aktif = generate_analisis_cuaca(
            client, 
            lokasi, 
            tgl_str, 
            data_points, 
        )
        
        # Gabungkan semua untuk dikirim ke WA
        footer = f"\n\n*--- ANALISA TANTE GEMINI ({model_aktif}) ---*\n"
        pesan_final = f"{header}{data_points}{footer}{analisa_teks}"
        
        return pesan_final

    except Exception as e:
        return f"⚠️ Gagal memproses data: {str(e)}"

@app.route('/proses', methods=['POST'])
def proses_pesan():
    data = request.json
    raw_text = data.get('text', '').strip()
    text_lower = raw_text.lower()
    image_path = data.get('image_path') # Asumsi gateway Node.js mengirimkan path file

    # KASUS Analisa Gambar (/spesies)
    if text_lower.startswith('/spesies') and image_path:
        if os.path.exists(image_path):
            try:
                hasil = generate_analisis_spesies(image_path)
            except Exception as e:
                hasil = f"⚠️ Gagal analisa: {str(e)}"
            finally:
                # Apapun yang terjadi (error/sukses), hapus fotonya!
                if os.path.exists(image_path):
                    os.remove(image_path)
                    print(f"🗑️ File {image_path} berhasil dibersihkan.")
            
            return jsonify({"reply": hasil})
        
    elif not text_lower.startswith('/cek'):
        return jsonify({"reply": None})

    # Default Settings (Botany Bay)
    lat, lon, lokasi_nama = -33.98, 151.23, "Botany Bay"
    target_dt = datetime.now()
    
    # LOCK JAM: Sesuai request Suhu 04:00 sampai 20:00
    jam_mulai_default = 4
    jam_selesai = 20

    # Tentukan jam_mulai secara dinamis jika untuk "Hari Ini"
    # Jika sekarang jam 10 pagi, laporan mulai dari jam 10.
    # Jika sekarang belum jam 4 pagi, laporan mulai dari jam 4.
    current_hour = datetime.now().hour
    jam_mulai = max(jam_mulai_default, current_hour)

    parts = raw_text.split()
    date_match = re.search(r'(\d{6})', raw_text)
    is_future = False
    
    # 1. Cek Tanggal Spesifik atau "Besok"
    if date_match:
        try:
            target_dt = datetime.strptime(date_match.group(1), "%d%m%y")
            jam_mulai = 4 # Untuk hari depan, tampilkan full dari jam 4
            is_future = True
        except: pass
    elif "besok" in text_lower:
        target_dt += timedelta(days=1)
        jam_mulai = 4 # Untuk besok, tampilkan full dari jam 4
        is_future = True

    # 2. Cek Lokasi Dinamis
    location_words = [p for p in parts[1:] if not p.isdigit() and p.lower() != "besok"]
    if location_words:
        user_loc = " ".join(location_words)
        new_lat, new_lon, clean_name = get_coordinates_data(user_loc)
        if new_lat:
            lat, lon, lokasi_nama = new_lat, new_lon, clean_name
        else:
            return jsonify({"reply": f"❓ Lokasi '{user_loc}' nggak ketemu, Om. Cek ejaan atau pake nama daerah diarea deket laut."})
    
    # 3. Mitigasi: Jika sudah lewat jam 8 malam (20:00)
    # Otomatis arahkan ke besok pagi jam 04:00
    if not is_future and current_hour >= 20:
        target_dt += timedelta(days=1)
        jam_mulai = 4
        lokasi_nama += " (Besok Pagi)"
        
    laporan = buat_laporan(lat, lon, lokasi_nama, target_dt, jam_mulai, jam_selesai, )
    return jsonify({"reply": laporan})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
