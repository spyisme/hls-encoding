require('dotenv').config();
const express = require('express');
const multer = require('multer');
const axios = require('axios');
const path = require('path');
const fs = require('fs');
const { CustomDriveAudit, getGDriveLinkId } = require('./download');

const app = express();
const PORT = process.env.PORT || 3000;

// In-memory job tracker
const jobs = new Map();

// Configure multer for video uploads
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    const uploadDir = path.join(__dirname, 'uploads');
    fs.mkdirSync(uploadDir, { recursive: true });
    cb(null, uploadDir);
  },
  filename: (req, file, cb) => {
    const uniqueName = `${Date.now()}-${file.originalname}`;
    cb(null, uniqueName);
  }
});
const upload = multer({ storage, limits: { fileSize: 5 * 1024 * 1024 * 1024 } }); // 5GB limit

// Middleware
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));
app.use('/uploads', express.static(path.join(__dirname, 'uploads')));

// ============ API Routes ============

// Upload video and trigger GitHub Actions encode
app.post('/api/upload', upload.single('video'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No video file uploaded.' });
    }

    const outputName = req.body.outputName || path.parse(req.file.originalname).name;
    const parentFolder = req.body.parentFolder || 'videos';
    const serverUrl = process.env.SERVER_PUBLIC_URL;
    const videoUrl = `${serverUrl}/uploads/${req.file.filename}`;
    const callbackWebhook = `${serverUrl}/api/webhook/complete`;

    const jobId = Date.now().toString(36) + Math.random().toString(36).substr(2, 5);

    // Trigger GitHub Actions Repository Dispatch
    await axios.post(
      `https://api.github.com/repos/${process.env.REPO_OWNER}/${process.env.REPO_NAME}/dispatches`,
      {
        event_type: 'trigger-encode',
        client_payload: {
          video_url: videoUrl,
          output_name: outputName,
          parent_folder: parentFolder,
          callback_webhook: callbackWebhook,
          job_id: jobId,
          source_type: 'direct'
        }
      },
      {
        headers: {
          Authorization: `token ${process.env.GITHUB_PAT}`,
          Accept: 'application/vnd.github.v3+json',
          'Content-Type': 'application/json'
        }
      }
    );

    // Store job metadata
    jobs.set(jobId, {
      id: jobId,
      outputName,
      parentFolder,
      originalFile: req.file.originalname,
      localFile: req.file.filename,
      source: 'upload',
      status: 'dispatched',
      startedAt: new Date().toISOString(),
      completedAt: null,
      timeTaken: null
    });

    res.json({ success: true, jobId, message: 'Encoding job dispatched to GitHub Actions.' });
  } catch (err) {
    console.error('Dispatch error:', err.response?.data || err.message);
    res.status(500).json({ error: 'Failed to dispatch encoding job.', details: err.response?.data || err.message });
  }
});

// Google Drive upload - verify accessibility then trigger encode
app.post('/api/g-drive/upload', async (req, res) => {
  try {
    const { driveUrl, outputName, parentFolder } = req.body;

    if (!driveUrl) {
      return res.status(400).json({ error: 'No Google Drive URL provided.' });
    }

    // Step 1: Extract file ID and verify accessibility
    const fileId = getGDriveLinkId(driveUrl);
    if (!fileId || fileId === driveUrl) {
      return res.status(400).json({ error: 'Invalid Google Drive URL. Please provide a valid sharing link.' });
    }

    console.log(`\n🔍 Verifying Google Drive file accessibility: ${fileId}`);
    const audit = await CustomDriveAudit(driveUrl);

    if (!audit.sizeFound) {
      console.log(`❌ File not accessible: ${audit.name} — ${audit.size}`);
      return res.status(403).json({
        error: 'File is not accessible. Please check the sharing permissions.',
        details: {
          fileName: audit.name,
          status: audit.size,
          fileId: audit.id
        }
      });
    }

    console.log(`✅ File verified: ${audit.name} (${audit.size})`);

    // Step 2: Dispatch GitHub Actions with gdrive source type
    const resolvedOutput = outputName || audit.name.replace(/\.[^.]+$/, '').replace(/[^a-zA-Z0-9-_]/g, '-') || 'gdrive-video';
    const resolvedFolder = parentFolder || 'videos';
    const serverUrl = process.env.SERVER_PUBLIC_URL;
    const callbackWebhook = `${serverUrl}/api/webhook/complete`;
    const jobId = Date.now().toString(36) + Math.random().toString(36).substr(2, 5);

    await axios.post(
      `https://api.github.com/repos/${process.env.REPO_OWNER}/${process.env.REPO_NAME}/dispatches`,
      {
        event_type: 'trigger-encode',
        client_payload: {
          source_type: 'gdrive',
          gdrive_file_id: fileId,
          gdrive_file_name: audit.name,
          output_name: resolvedOutput,
          parent_folder: resolvedFolder,
          callback_webhook: callbackWebhook,
          job_id: jobId
        }
      },
      {
        headers: {
          Authorization: `token ${process.env.GITHUB_PAT}`,
          Accept: 'application/vnd.github.v3+json',
          'Content-Type': 'application/json'
        }
      }
    );

    // Store job metadata
    jobs.set(jobId, {
      id: jobId,
      outputName: resolvedOutput,
      parentFolder: resolvedFolder,
      originalFile: `[GDrive] ${audit.name}`,
      localFile: null,
      source: 'gdrive',
      driveFileId: fileId,
      driveFileSize: audit.size,
      status: 'dispatched',
      startedAt: new Date().toISOString(),
      completedAt: null,
      timeTaken: null
    });

    res.json({
      success: true,
      jobId,
      message: 'Google Drive encoding job dispatched to GitHub Actions.',
      fileInfo: { name: audit.name, size: audit.size, id: fileId }
    });
  } catch (err) {
    console.error('GDrive dispatch error:', err.response?.data || err.message);
    res.status(500).json({ error: 'Failed to dispatch Google Drive encoding job.', details: err.response?.data || err.message });
  }
});

// Webhook endpoint - GitHub Actions calls this when done
app.post('/api/webhook/complete', (req, res) => {
  const { status, output_name, time_taken_seconds } = req.body;
  console.log(`\n✅ Webhook received: ${output_name} — Status: ${status} — Time: ${time_taken_seconds}s`);

  // Find and update the matching job
  for (const [id, job] of jobs) {
    if (job.outputName === output_name && job.status === 'dispatched') {
      job.status = status === 'success' ? 'completed' : 'failed';
      job.completedAt = new Date().toISOString();
      job.timeTaken = time_taken_seconds ? `${time_taken_seconds}s` : 'unknown';

      // Clean up the uploaded source file (only for direct uploads)
      if (job.localFile) {
        const filePath = path.join(__dirname, 'uploads', job.localFile);
        if (fs.existsSync(filePath)) {
          fs.unlinkSync(filePath);
          console.log(`🗑️  Cleaned up source file: ${job.localFile}`);
        }
      }
      break;
    }
  }

  res.json({ received: true });
});

// Get all jobs
app.get('/api/jobs', (req, res) => {
  const allJobs = Array.from(jobs.values()).sort((a, b) =>
    new Date(b.startedAt) - new Date(a.startedAt)
  );
  res.json(allJobs);
});

// Health check
app.get('/api/health', (req, res) => {
  res.json({ status: 'online', uptime: process.uptime(), jobCount: jobs.size });
});

// ============ Start Server ============
app.listen(PORT, () => {
  console.log(`\n🚀 HLS Encoding Dashboard running at http://localhost:${PORT}`);
  console.log(`📡 Webhook endpoint: ${process.env.SERVER_PUBLIC_URL}/api/webhook/complete`);
  console.log(`📂 Repo target: ${process.env.REPO_OWNER}/${process.env.REPO_NAME}\n`);
});
