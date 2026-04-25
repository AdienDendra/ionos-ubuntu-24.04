import os
import requests
import re
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from dateutil import parser
from google import genai
from geopy.geocoders import Nominatim
import config

NAMA_HARI = {
    "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
    "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"
}

NAMA_BULAN = {
    "January": "Januari", "February": "Februari", "March": "Maret", "April": "April",
    "May": "Mei", "June": "Juni", "July": "Juli", "August": "Agustus",
    "September": "September", "October": "Oktober", "November": "November", "December": "Desember"
}

app = Flask(__name__)

# Setup Gemini & Geocoder
client = genai.Client(api_key=config.API_KEY_GEMINI)
geolocator = Nominatim(user_agent="bot_mancing_sydney_pro_adien")

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

def get_weather(lat, lon):
    url_m = f"https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}&hourly=wave_height,swell_wave_height,swell_wave_period&timezone=auto&forecast_days=7"
    # Tambah temperature_2m dan surface_pressure di Weather API
    url_w = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=wind_speed_10m,temperature_2m,surface_pressure&timezone=auto&forecast_days=7"
    
    return requests.get(url_m).json(), requests.get(url_w).json()
def buat_laporan(lat, lon, lokasi, target_dt, jam_mulai, jam_selesai):
    try:
        marine, weather = get_weather(lat, lon)
        diff_days = (target_dt.date() - datetime.now().date()).days
        
        # Safety check untuk data API
        if 'hourly' not in marine or 'hourly' not in weather:
            return f"❌ Data cuaca untuk {lokasi} gagal diambil dari satelit, Om."
        start_idx = diff_days * 24
        
        # Ambil nama hari dan bulan dalam bahasa Inggris dulu
        hari_en = target_dt.strftime("%A")
        tgl_angka = target_dt.strftime("%d")
        bulan_en = target_dt.strftime("%B")
        tahun = target_dt.strftime("%Y")

        # Terjemahkan menggunakan dictionary
        hari_id = NAMA_HARI.get(hari_en, hari_en)
        bulan_id = NAMA_BULAN.get(bulan_en, bulan_en)

        # Gabungkan kembali
        tgl_str = f"{hari_id}, {tgl_angka} {bulan_id} {tahun}"
        
        header = f"*LAPORAN PRAKIRAAN MANCING: {lokasi.upper()}*\n📅 {tgl_str}\n"
        header += "-"*30 + "\n"

        data_points = ""
        count = 0
        for i in range(24):
            idx = start_idx + i
            if idx >= len(marine['hourly']['time']): break
            
            jam = parser.isoparse(marine['hourly']['time'][idx]).hour
            
            # LOGIKA FILTER JAM YANG LEBIH AMAN
            if jam_mulai <= jam <= jam_selesai:
                wv = marine['hourly']['wave_height'][idx]
                sw = marine['hourly']['swell_wave_height'][idx]
                wind = weather['hourly']['wind_speed_10m'][idx]
                # Data Baru (Swell Period, Temp, Pressure)
                swp = marine['hourly']['swell_wave_period'][idx]
                temp = weather['hourly']['temperature_2m'][idx]
                pres = weather['hourly']['surface_pressure'][idx]
                
                # Letakkan garis di ATAS data jam agar rapi
                data_points += "--------------------------\n"
                data_points += f"Jam {jam:02d}:00\n"
                data_points += f"🌬️ Angin: {wind} km/h\n"
                data_points += f"🌊 Wave: {wv}m | Swell: {sw}m\n"
                data_points += f"⏱️ Period: {swp}s\n"
                data_points += f"🌡️ Temp: {temp}°C | Pres: {pres}hPa\n"
                count += 1

        # MITIGASI: Jika sudah terlalu malam untuk hari ini
        if count == 0:
            return f"❌ Jam mancing di {lokasi} sudah lewat untuk hari ini. Coba ketik: `/cek tanggalbulantahun` atau `/cek {lokasi} tanggalbulantahun`."

        # --- LOGIKA AI FAILOVER DENGAN DEBUGGING ---
        daftar_model = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash']
        response = None
        model_terpakai = ""

        # --- REVISI DI DALAM buat_laporan ---
        for md in daftar_model:
            try:
                # Kita buat prompt lebih fleksibel agar Gemini tidak bingung
                prompt = (
                    f"Instruksi: {config.INSTRUKSI_AI}\n\n"
                    f"Analisa cuaca untuk lokasi: {lokasi}\n"
                    f"Tanggal: {tgl_str}\n"
                    f"Data: \n{data_points}"
                )
                
                res = client.models.generate_content(model=md, contents=prompt)
                if res and res.text:
                    response = res
                    model_terpakai = md
                    break 
            except Exception as e:
                print(f"⚠️ Debug: {md} gagal: {str(e)}")
                continue

        if not response:
            # Hapus tulisan (Botany Bay Default) agar tidak membingungkan
            return f"{header}{data_points}\n⚠️ *Tante Gemini lagi dandan (API Busy), tapi ini data mentahnya ya Om.*"
        
        return f"{header}{data_points}\n*--- ANALISA TANTE GEMINI ({model_terpakai}) ---*\n{response.text}"
        
    except Exception as e:
        print(f"🔥 Error Detail: {str(e)}")
        return f"⚠️ Error Dapur: {str(e)}"

@app.route('/proses', methods=['POST'])
def proses_pesan():
    data = request.json
    raw_text = data.get('text', '').strip()
    text_lower = raw_text.lower()
    
    if not text_lower.startswith('/cek'):
        return jsonify({"reply": None})

    # Default Settings
    lat, lon, lokasi_nama = -33.98, 151.23, "Botany Bay"
    target_dt = datetime.now()
    
    # ATURAN JAM SESUAI REQUEST:
    # Jika hanya /cek (tanpa lokasi/tanggal) -> s/d jam 19 (7 malam)
    # Jika ada lokasi atau tanggal -> s/d jam 20 (8 malam)
    jam_mulai = datetime.now().hour
    jam_selesai = 19 

    parts = raw_text.split()
    date_match = re.search(r'(\d{6})', raw_text)
    is_special = False
    
    # 1. Cek Tanggal/Besok
    if date_match:
        try:
            target_dt = datetime.strptime(date_match.group(1), "%d%m%y")
            jam_mulai, jam_selesai, is_special = 4, 20, True
        except: pass
    elif "besok" in text_lower:
        target_dt += timedelta(days=1)
        jam_mulai, jam_selesai, is_special = 4, 20, True

    # 2. Cek Lokasi
    location_words = [p for p in parts[1:] if not p.isdigit() and p.lower() != "besok"]
    if location_words:
        user_loc = " ".join(location_words)
        new_lat, new_lon, clean_name = get_coordinates(user_loc)
        if new_lat:
            lat, lon, lokasi_nama = new_lat, new_lon, clean_name
            jam_selesai = 20 # Sesuai request: lokasi dinamis s/d jam 8 malam
        else:
            # Jika typo, jangan diam saja, beri feedback
            return jsonify({"reply": f"❓ Lokasi '{user_loc}' nggak ketemu di peta, Om. Coba cek ejaannya atau pake nama daerah yang lebih umum."})
    
    # Jika sudah di atas jam 7 malam dan user cuma ngetik /cek, 
    # otomatis arahkan ke besok pagi daripada kasih pesan error jam lewat.
    if not is_special and not location_words and jam_mulai >= 19:
        target_dt += timedelta(days=1)
        jam_mulai = 4
        jam_selesai = 20
        # Opsional: beri tahu user ini data besok
        lokasi_nama += " (Edisi Besok)"
        
    laporan = buat_laporan(lat, lon, lokasi_nama, target_dt, jam_mulai, jam_selesai)
    return jsonify({"reply": laporan})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
