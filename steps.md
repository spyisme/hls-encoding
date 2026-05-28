# 🚀 Setup & Running Guide — HLS Cloud Encoder

Follow these steps **in order** to get the system fully operational.

---

## Step 1: Create a GitHub Repository

1. Go to [github.com/new](https://github.com/new)
2. Create a **new repository** (e.g. `hls-cloud-encoder`)
3. Set it to **Private** (recommended)
4. Do **NOT** initialize with a README (you'll push this existing code)

---

## Step 2: Push This Code to GitHub

Open a terminal in this project folder and run:

```bash
git add .
git commit -m "Initial commit: HLS Cloud Encoder"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git push -u origin main
```

> Replace `YOUR_USERNAME` and `YOUR_REPO_NAME` with your actual values.

---

## Step 3: Configure GitHub Repository Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these **4 secrets**:

| Secret Name            | Value                                                                 |
|------------------------|-----------------------------------------------------------------------|
| `R2_ACCESS_KEY_ID`     | Your Cloudflare R2 S3-compatible Access Key ID                        |
| `R2_SECRET_ACCESS_KEY` | Your Cloudflare R2 S3-compatible Secret Access Key                    |
| `R2_BUCKET_NAME`       | Your R2 bucket name (e.g. `my-videos`)                                |
| `R2_ENDPOINT`          | Your R2 S3 API endpoint (e.g. `https://<account_id>.r2.cloudflarestorage.com`) |

### How to get R2 credentials:
1. Log into [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Go to **R2 Object Storage** → create a bucket if you don't have one
3. Go to **R2** → **Manage R2 API Tokens** → **Create API Token**
4. Give it **Object Read & Write** permissions for your bucket
5. Copy the **Access Key ID**, **Secret Access Key**, and **Endpoint URL**

---

## Step 4: Generate a GitHub Personal Access Token (PAT)

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
2. Click **Generate new token (classic)**
3. Give it a name (e.g. `HLS Encoder`)
4. Select the **`repo`** scope (full control of private repositories)
5. Click **Generate token** and **copy it immediately**

---

## Step 5: Create the Local `.env` File

In the project root, copy the example and fill in your values:

```bash
cp .env.example .env
```

Then edit `.env`:

```env
GITHUB_PAT=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
REPO_OWNER=your-github-username
REPO_NAME=hls-cloud-encoder
SERVER_PUBLIC_URL=https://your-ngrok-url.ngrok-free.app
PORT=3000
```

> ⚠️ **`SERVER_PUBLIC_URL`** must be a publicly accessible URL. See next step.

---

## Step 6: Install Dependencies

```bash
npm install
```

---

## Step 7: Expose Your Local Server (ngrok)

GitHub Actions needs to download the uploaded video from your machine and send back a webhook. You need a public tunnel:

### Option A: ngrok (recommended for testing)

1. Install ngrok: [ngrok.com/download](https://ngrok.com/download)
2. Sign up for a free account and authenticate:
   ```bash
   ngrok config add-authtoken YOUR_NGROK_TOKEN
   ```
3. Start the tunnel:
   ```bash
   ngrok http 3000
   ```
4. Copy the **Forwarding URL** (e.g. `https://abc123.ngrok-free.app`)
5. **Paste it** into your `.env` as `SERVER_PUBLIC_URL`

### Option B: Cloudflare Tunnel (more permanent)
```bash
cloudflared tunnel --url http://localhost:3000
```

---

## Step 8: Start the Server

```bash
npm start
```

You should see:
```
🚀 HLS Encoding Dashboard running at http://localhost:3000
📡 Webhook endpoint: https://your-url.ngrok-free.app/api/webhook/complete
📂 Repo target: your-username/hls-cloud-encoder
```

---

## Step 9: Open the Dashboard & Encode!

1. Open **http://localhost:3000** in your browser
2. Drag & drop a video file (MP4, MKV, MOV, AVI)
3. Set an output name and parent folder
4. Click **🚀 Start Encoding Pipeline**
5. The job will appear in the jobs table with `dispatched` status
6. Wait for GitHub Actions to finish (~5-20 min depending on video size)
7. Status will update to `completed` when the webhook fires back

---

## ✅ Verification Checklist

- [ ] GitHub repo created and code pushed
- [ ] 4 R2 secrets added to GitHub repo settings
- [ ] GitHub PAT generated with `repo` scope
- [ ] `.env` file created with all values filled
- [ ] `npm install` completed
- [ ] ngrok (or tunnel) running with public URL
- [ ] `SERVER_PUBLIC_URL` in `.env` matches the tunnel URL
- [ ] Server running via `npm start`
- [ ] Dashboard accessible at http://localhost:3000

---

## 🔍 Troubleshooting

| Issue | Solution |
|-------|---------|
| Upload works but GitHub Action doesn't start | Check `GITHUB_PAT` has `repo` scope. Check repo name matches. |
| Action starts but fails at download | Ensure `SERVER_PUBLIC_URL` is publicly reachable and ngrok is running. |
| Action succeeds but webhook never arrives | Verify ngrok is still active. Check `callback_webhook` in Actions logs. |
| R2 upload fails | Verify all 4 R2 secrets. Test `rclone` config manually. |
| "Resource not accessible by integration" | PAT needs to be a **Classic** token with `repo` scope, not a fine-grained token. |

---

## 📁 Project Structure

```
├── .github/
│   └── workflows/
│       └── encode.yml          # GitHub Actions encoding pipeline
├── public/
│   ├── index.html              # Web dashboard (glassmorphism UI)
│   └── player.html             # NEW: Premium HLS Stream Player
├── .env.example                # Environment variable template
├── .gitignore                  # Ignores node_modules, uploads, .env
├── package.json                # Node.js dependencies
├── server.js                   # Express backend server
├── main.md                     # System architecture blueprint
└── steps.md                    # This setup guide
```
