/* QR scanning with the camera through Chrome's built-in BarcodeDetector (no library). */

export const canScan = () => "BarcodeDetector" in window && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

/** Show the back camera in `video` and call `onCode(text)` for each QR read; returns stop(). */
export async function startScan(video, onCode) {
  const formats = await window.BarcodeDetector.getSupportedFormats();
  if (!formats.includes("qr_code")) throw new Error("Questo telefono non legge i codici QR: incolla il testo.");
  const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
  } catch (e) {
    throw new Error("Fotocamera non disponibile: consenti l'accesso o incolla il testo.");
  }
  video.srcObject = stream;
  video.setAttribute("playsinline", "");
  await video.play();
  let stopped = false;
  let last = "";
  const loop = async () => {
    if (stopped) return;
    try {
      const codes = await detector.detect(video);
      for (const c of codes) {
        if (c.rawValue && c.rawValue !== last) { last = c.rawValue; onCode(c.rawValue); }
      }
    } catch (e) { /* frame not ready */ }
    if (!stopped) setTimeout(loop, 200);
  };
  loop();
  return function stop() {
    stopped = true;
    stream.getTracks().forEach((t) => t.stop());
    video.srcObject = null;
  };
}
