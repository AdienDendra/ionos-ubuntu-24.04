const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, downloadMediaMessage } = require("@whiskeysockets/baileys");
const { Boom } = require("@hapi/boom");
const axios = require("axios");
const pino = require("pino");
const fs = require("fs"); // <-- untuk tulis file
const path = require("path"); // <--  ini untuk atur path

async function startBot() {
    // Membaca folder auth_info yang baru saja Suhu upload/unzip
    const { state, saveCreds } = await useMultiFileAuthState('auth_info');
    const { version } = await fetchLatestBaileysVersion();

    const sock = makeWASocket({
        auth: state,
        version,
        logger: pino({ level: 'silent' }),
        browser: ["Ubuntu", "Chrome", "20.0.04"], // Identitas agar tidak dicurigai
        connectTimeoutMs: 60000,
        defaultQueryTimeoutMs: 0,
        keepAliveIntervalMs: 10000
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect } = update;
        if (connection === 'close') {
            const shouldReconnect = (lastDisconnect.error instanceof Boom)?.output?.statusCode !== DisconnectReason.loggedOut;
            console.log('❌ Koneksi terputus di VPS. Mencoba hubungkan ulang:', shouldReconnect);
            if (shouldReconnect) startBot();
        } else if (connection === 'open') {
            console.log('✅ AMIS TOTAL! Pelayan Node.js di VPS sudah terhubung menggunakan sesi lokal.');
        }
    });

    sock.ev.on('messages.upsert', async ({ messages }) => {
        const m = messages[0];
        if (!m.message || m.key.fromMe) return;
        
        const mimeType = m.message.imageMessage?.mimetype || "image/jpeg";
        const remoteJid = m.key.remoteJid;
        
        // 2. Logika Menangkap Teks (Chat Biasa atau Caption Gambar)
        const pesanText = m.message.conversation || 
                          m.message.extendedTextMessage?.text || 
                          m.message.imageMessage?.caption || ""; // <-- Cek caption gambar
        
        const command = pesanText.toLowerCase();

        // JALUR A: ANALISA GAMBAR (/spesies)
        if (command.startsWith('/spesies')) {
            const isImage = !!m.message.imageMessage;
            
            if (!isImage) {
                return await sock.sendMessage(remoteJid, { text: "Mana fotonya Om? Kirim gambar terus kasih caption /spesies ya." });
            }

            console.log(`📸 Proses Analisa Spesies dari: ${remoteJid}`);
            
            try {
                // Download gambar dari WA
                const buffer = await downloadMediaMessage(m, 'buffer', {});
                
                // Simpan ke folder sesi-mancing
                const fileName = `img_${Date.now()}.jpg`;
                const filePath = path.join(__dirname, '../sesi-mancing', fileName);
                fs.writeFileSync(filePath, buffer);

                // Kirim Path ke Python
                const response = await axios.post('http://127.0.0.1:5000/proses', {
                    text: pesanText,
                    image_path: filePath,
                    mime_type: mimeType,
                    sender: remoteJid
                });

                if (response.data.reply) {
                    await sock.sendMessage(remoteJid, { text: response.data.reply });
                }
            } catch (error) {
                console.error("⚠️ Gagal di Jalur Visual:", error.message);
                await sock.sendMessage(remoteJid, { text: "Waduh, server lagi pusing pas liat foto. Coba lagi Om!" });
            }
        }

        // JALUR B: CEK CUACA (/cek)
        else if (command.startsWith('/cek')) {
            console.log(`📩 Pesan Cuaca: ${pesanText}`);
            try {
                const response = await axios.post('http://127.0.0.1:5000/proses', {
                    text: pesanText,
                    sender: remoteJid
                });

                if (response.data.reply) {
                    await sock.sendMessage(remoteJid, { text: response.data.reply });
                }
            } catch (error) {
                console.error("⚠️ Gagal di Jalur Cuaca:", error.message);
            }
        }
    });
}

console.log("🚀 Menjalankan Pelayan Node.js di VPS...");
startBot();
