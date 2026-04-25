const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = require("@whiskeysockets/baileys");
const { Boom } = require("@hapi/boom");
const axios = require("axios");
const pino = require("pino");

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

        const pesanText = m.message.conversation || m.message.extendedTextMessage?.text || "";
        const remoteJid = m.key.remoteJid;

        if (pesanText.toLowerCase().startsWith('/cek')) {
            console.log(`📩 Pesan masuk di VPS: ${pesanText}`);
            try {
                // Pastikan Python main.py sudah jalan di port 5000 VPS
                const response = await axios.post('http://127.0.0.1:5000/proses', {
                    text: pesanText,
                    sender: remoteJid
                });

                if (response.data.reply) {
                    await sock.sendMessage(remoteJid, { text: response.data.reply });
                }
            } catch (error) {
                console.error("⚠️ Gagal kontak Dapur Python di VPS:", error.message);
            }
        }
    });
}

console.log("🚀 Menjalankan Pelayan Node.js di VPS...");
startBot();
