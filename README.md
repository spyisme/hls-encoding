# ⚡ HLS Cloud Encoder

An ultra-low cost, hybrid pipeline that transcodes high-quality HLS streams by offloading heavy video encoding to **GitHub Actions** and distributing them globally using **Cloudflare R2**.

---

## 📐 How it Works

The entire workflow is split into 3 simple steps:

1. **Upload**: Drag-and-drop a video onto your local Express server dashboard.
2. **Transcode**: The server triggers a remote **GitHub Actions** runner to download the video, detect its vertical resolution (to prevent wasteful upscaling), and transcode it using FFmpeg.
3. **Host**: The runner syncs the finished multi-bitrate HLS files (`.m3u8`, `.ts`) and a poster image (`thumbnail.jpg`) directly to your **Cloudflare R2** bucket, then alerts your local server to clean up the source files.

---

## 💸 Cost Comparison (1 TB Storage + 5 TB Streaming Egress / Month)

Typical hosting providers penalize video delivery with heavy data transfer (egress) fees. Because **Cloudflare R2 charges \$0.00 egress**, operational costs remain completely flat:

| Platform | Storage Cost (1 TB) | Egress Bandwidth Cost (5 TB) | Total Monthly Cost |
| :--- | :--- | :--- | :--- |
| **AWS S3 + CloudFront** | \$23.00 | \$450.00 | **\$473.00** |
| **Bunny CDN (Storage & Stream)** | \$10.00 | \$25.00 | **\$35.00** |
| **Cloudflare R2 + GitHub Actions** | \$15.00 | **\$0.00** (Free egress) | **\$15.00** (Flat) |

---

## 🚀 Quick Start

Get your local server and preview dashboard running in three simple commands:

```bash
# 1. Install dependencies
npm install

# 2. Configure credentials (copy the template and fill in your values)
cp .env.example .env

# 3. Launch the server
npm start
```

*Note: For the full step-by-step setup regarding GitHub Secrets, PAT tokens, and ngrok tunneling configurations, see [steps.md](file:///C:/Users/Spy/Desktop/cheap%20video%20encoding/steps.md).*

---

## 💖 Credits

Inspired by the cloud video encoding architecture from [developedbyed](https://www.youtube.com/@developedbyed) on YouTube.

