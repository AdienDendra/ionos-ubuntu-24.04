import os
import requests
import re
from flask import Flask, request, jsonify
from datetime import datetime, timedelta, timezone
from dateutil import parser
from google import genai
from geopy.geocoders import Nominatim
from config import INSTRUKSI_AI, LUNAR_ANCHOR, LUNATION_CYCLE
import math
import os
from dotenv import load_dotenv

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

def get_astronomy_data(target_dt, lat, lon):
    # 1. Base Time & Moon Phase (Global)
    dt_utc = target_dt.replace(hour=12, minute=0) - timedelta(hours=10)
    diff = dt_utc - LUNAR_ANCHOR
    days_since_new_moon = diff.total_seconds() / 86400
    phase = (days_since_new_moon / LUNATION_CYCLE) % 1

    # 2. Moon Transit (Longitude Dependent)
    location_correction = (lon / 15.0)
    days_in_cycle = days_since_new_moon % LUNATION_CYCLE
    transit_base = (days_in_cycle / LUNATION_CYCLE) * 24
    
    major_1_center = (12 + transit_base - location_correction + 10) % 24
    major_2_center = (major_1_center + 12) % 24
    minor_1_center = (major_1_center - 6) % 24
    minor_2_center = (major_1_center + 6) % 24

    # 3. SUNRISE/SUNSET (LATITUDE & SEASON DEPENDENT)
    # Menghitung hari ke-berapa dalam setahun (1-365)
    day_of_year = target_dt.timetuple().tm_yday
    
    # Menghitung deklinasi matahari (kemiringan bumi terhadap matahari)
    # Rumus: -23.44 * cos(360/365 * (N + 10))
    declination = -23.44 * math.cos(math.radians(360/365 * (day_of_year + 10)))
    
    # Menghitung Hour Angle (kapan matahari menyentuh cakrawala)
    # Ini melibatkan Latitude (lat) Suhu!
    lat_rad = math.radians(lat)
    dec_rad = math.radians(declination)
    
    # Rumus durasi siang (Hour Angle)
    # cos(h) = -tan(lat) * tan(dec)
    try:
        cos_h = -math.tan(lat_rad) * math.tan(dec_rad)
        # Batasi nilai agar tidak error (di kutub saat polar night/day)
        cos_h = max(min(cos_h, 1.0), -1.0)
        h_angle = math.degrees(math.acos(cos_h)) / 15.0 # Konversi ke jam
    except:
        h_angle = 6.0 # Default jika kalkulasi gagal

    # Sunrise/Sunset Dasar (Solar Noon adalah ~12:00)
    # Dikoreksi dengan Longitude dan durasi siang (h_angle)
    sr_base = 12.0 - h_angle - (location_correction - 10)
    ss_base = 12.0 + h_angle - (location_correction - 10)

    # 4. Helper Formatting
    def fmt_time(h):
        h = h % 24
        return f"{int(h):02d}:{int((h % 1) * 60):02d}"

    def fmt_range(center):
        return f"{fmt_time(center-1)} - {fmt_time(center+1)}"

    is_good_phase = phase < 0.1 or 0.4 < phase < 0.6 or phase > 0.9
    major_emoji = "🐟🐟🔥 *JOSSS!!:* " if is_good_phase else "🐟🐟 *Major:* "

    return {
        "sr": fmt_time(sr_base), 
        "ss": fmt_time(ss_base),
        "major": f"{major_emoji}{fmt_range(major_2_center)} & {fmt_range(major_1_center)}",
        "minor": f"🐟 *Minor:* {fmt_range(minor_2_center)} & {fmt_range(minor_1_center)}",
        "low": f"💤 *Low:* di luar periode Major dan Minor"
    }

def get_coordinates(location_name):
    """Mitigasi typo dan pencarian lokasi dinamis"""
    try:
        # Kunci pencarian di wilayah Australia agar akurat
        query = f"{location_name}, Australia"
        location = geolocator.geocode(query, timeout=10)
        if location:
            short_name = location.address.split(',')[0]
            return location.latitude, location.longitude, short_name
        return None, None, None
    except:
        return None, None, None
    
def find_nearest_sea_cell(lat, lon):
    # Pola Radar: Cek titik asli, lalu melingkar menjauh
    # 0.025 derajat ~ 2.75km
    # 0.075 derajat ~ 8km
    search_pattern = [
    # Langkah 1: Cek radius menengah (~2.75km) ke 4 arah utama
        (0, 0.025),   # Timur (Sydney/NSW)
        (0, -0.025),  # Barat (Perth/WA)
        (0.025, 0),   # Utara (Darwin/NT)
        (-0.025, 0),  # Selatan (Adelaide/VIC)

        # Langkah 2: Cek Diagonal (Penting untuk garis pantai yang miring)
        (0.025, 0.025), (0.025, -0.025), (-0.025, 0.025), (-0.025, -0.025),

        # Langkah 3: Cek radius jauh (~8km) jika lokasi di dalam teluk dalam
        (0, 0.075), (0, -0.075), (0.075, 0), (-0.075, 0)
    ]
    for d_lat, d_lon in search_pattern:
        t_lat, t_lon = round(lat + d_lat, 4), round(lon + d_lon, 4)
        
        url_check = f"https://marine-api.open-meteo.com/v1/marine?latitude={t_lat}&longitude={t_lon}&hourly=wave_height&forecast_days=1"
        
        try:
            r = requests.get(url_check, timeout=2).json()
            # Kuncinya: Cari titik pertama yang koordinatnya dianggap 'Sea' oleh Open-Meteo
            if 'hourly' in r and r['hourly'].get('wave_height') and r['hourly']['wave_height'][0] is not None:
                print(f"✅ Lokasi Laut Ditemukan ({t_lat}, {t_lon}) untuk input ({lat}, {lon})")
                return t_lat, t_lon
        except:
            continue
            
    return lat, lon
    
def get_tide_data(lat, lon):
    """
    Fungsi khusus mengambil data pasang surut dari Open-Meteo.
    Data ini berbasis harmonic model (prediksi matematis).
    """
    url_t = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=tide_height&timezone=auto"
    try:
        r = requests.get(url_t, timeout=5).json()
        if 'hourly' in r and 'tide_height' in r['hourly']:
            return r['hourly']['tide_height']
    except Exception as e:
        print(f"⚠️ Error Tide Fetch: {e}")
    return None
   
def get_weather(lat, lon):
    # Langkah 1: Cari koordinat laut terdekat (Spiral Search)
    sea_lat, sea_lon = find_nearest_sea_cell(lat, lon)
    
    res_m = {"hourly": {}}
    res_w = {"hourly": {}}
    res_t = None # Untuk data tide

    try:
        # 2. Ambil Cuaca Daratan (Lokasi asli user)
        url_w = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=wind_speed_10m,temperature_2m,precipitation,precipitation_probability,surface_pressure&timezone=auto&forecast_days=7"
        res_w = requests.get(url_w, timeout=5).json()

        # 3. Ambil Data Marine (Wave, Swell, Period) di sea_lat/lon
        url_m = f"https://marine-api.open-meteo.com/v1/marine?latitude={sea_lat}&longitude={sea_lon}&hourly=wave_height,swell_wave_height,swell_wave_period&timezone=auto"
        res_m = requests.get(url_m, timeout=5).json()
        
        # 4. Ambil Data Tide (Panggil fungsi terpisah)
        res_t = get_tide_data(sea_lat, sea_lon)

    except Exception as e:
        print(f"🔥 Error Fetching Data: {e}")

    # Return ditambah res_t
    return res_m, res_w, res_t, sea_lat, sea_lon

def buat_laporan(lat, lon, lokasi, target_dt, jam_mulai, jam_selesai):
    try:
        # 1. AMBIL DATA (Sudah include dynamic ocean discovery)
        marine, weather, tide_data, f_lat, f_lon = get_weather(lat, lon)     

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
        analisa_teks, model_aktif = generate_ai_analysis(
            client, 
            lokasi, 
            tgl_str, 
            data_points, 
            INSTRUKSI_AI
        )
        
        # Gabungkan semua untuk dikirim ke WA
        footer = f"\n\n*--- ANALISA TANTE GEMINI ({model_aktif}) ---*\n"
        pesan_final = f"{header}{data_points}{footer}{analisa_teks}"
        
        return pesan_final

    except Exception as e:
        return f"⚠️ Gagal memproses data: {str(e)}"


def generate_ai_analysis(client, lokasi, tgl_str, data_points, instruksi_ai):
    """
    Fungsi dengan list model terbaru termasuk 2.0 dan 2.5
    """
    # List model: 2.5 dan 2.0 biasanya stabil di pertengahan 2026
    model_list = [
        'gemini-2.5-flash-lite',
        'gemini-2.5-flash',      # Jagoan terbaru
        'gemini-2.0-flash',      # Versi stabil 2.0
        'gemini-1.5-flash',      # Si Badak (Fallback utama)
        'gemini-1.5-flash-8b'   # Cadangan terakhir
    ]
    
    ai_response = "⚠️ *Analisa AI sedang sibuk, Om.*"
    model_used = "None"

    # Definisikan prompt di LUAR loop try agar aman
    prompt_text = (
        f"Instruksi: {instruksi_ai}\n"
        f"LOKASI: {lokasi}\n"
        f"TANGGAL: {tgl_str}\n"
        f"DATA CUACA:\n{data_points}"
    )

    print(f"\n🧠 Memulai Analisa AI untuk {lokasi}...")

    for md in model_list:
        try:
            print(f"📡 Mencoba model: {md}...") 
            
            # Panggil Gemini - Kita coba tanpa prefix 'models/' dulu
            # Jika masih 404, baru kita tambahkan prefixnya
            res = client.models.generate_content(
                model=md, 
                contents=prompt_text
            )
            
            if res and res.text:
                ai_response = res.text
                model_used = md
                print(f"✅ Berhasil pakai: {md}")
                break 
                
        except Exception as e:
            # Jika gagal karena 404, coba pakai prefix models/ secara otomatis
            if "not found" in str(e).lower():
                try:
                    print(f"🔄 Mencoba ulang {md} dengan prefix models/...")
                    res = client.models.generate_content(
                        model=f"models/{md}", 
                        contents=prompt_text
                    )
                    if res and res.text:
                        ai_response = res.text
                        model_used = md
                        print(f"✅ Berhasil pakai: models/{md}")
                        break
                except:
                    pass
            
            print(f"❌ {md} Gagal: {str(e)[:100]}")
            continue

    return ai_response, model_used

@app.route('/proses', methods=['POST'])
def proses_pesan():
    data = request.json
    raw_text = data.get('text', '').strip()
    text_lower = raw_text.lower()
    
    if not text_lower.startswith('/cek'):
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
        new_lat, new_lon, clean_name = get_coordinates(user_loc)
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
        
    laporan = buat_laporan(lat, lon, lokasi_nama, target_dt, jam_mulai, jam_selesai)
    return jsonify({"reply": laporan})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
