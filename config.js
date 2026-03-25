// Jay's Tire Shop — API configuration
// After deploying to Railway, replace the URL below with your Railway app URL.
// You only need to change this one file — all pages use window.JTS_API_URL.

window.JTS_API_URL = (
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1'
)
    ? 'http://localhost:5000/api'
    : 'https://YOUR-RAILWAY-APP.up.railway.app/api'; // ← Replace after Railway deploy
