# Cloud-Scale Distributed HLS Encoding System

This blueprint details a high-efficiency video transcoding deployment using a hybrid architecture. Heavy video transcoding tasks are completely offloaded to **GitHub Actions** infrastructure to tap into the free runner minutes allocation (2,000–3,000 mins/mo). The generated HLS multi-bitrate streams are directly published to **Cloudflare R2** for cost-effective global CDN distribution.

---

## 🛠️ System Prerequisites & Configuration Keys

### Required Secrets & Environment Variables

#### Cloudflare R2 Credentials
Configure these as **GitHub Repository Secrets** (`Settings -> Secrets and Variables -> Actions`):
* `R2_ACCESS_KEY_ID`: Cloudflare API token or S3-compatible Access Key.
* `R2_SECRET_ACCESS_KEY`: Cloudflare API token or S3-compatible Secret Key.
* `R2_BUCKET_NAME`: The target R2 bucket name where videos will be stored.
* `R2_ENDPOINT`: The custom S3 API endpoint provided by your R2 bucket dashboard (e.g., `https://<account_id>.r2.cloudflarestorage.com`).

#### GitHub API Access (For Local Dashboard App)
Configure these inside a local `.env` file on your host machine/Web UI server:
* `GITHUB_PAT`: A GitHub **Personal Access Token (Classic)** with full `repo` scopes to trigger repository dispatch events and pull runtime logs.
* `REPO_OWNER`: Your GitHub account username.
* `REPO_NAME`: Your encoding script repository name.
* `SERVER_PUBLIC_URL`: The public-facing HTTP address of your local server (e.g., an `ngrok` tunnel domain during testing) so GitHub can download uploaded media and fire back completed webhooks.

### Client-Side Server Requirements
The local server hosting the user interface relies purely on JavaScript runtime packages. **No operating-system level installations (like FFmpeg or Rclone) are required locally.**
* `express`: For web asset hosting and HTTP handling routing.
* `multer`: To parse binary incoming multipart video form data uploads.
* `axios`: For handling backend GitHub API communication sequences.
* `dotenv`: To load runtime credentials seamlessly.

---

## 📐 Architecture Workflow Blueprint

1. **User Action:** The client dashboard uploads an MP4 video to the local Web UI server.
2. **Buffering Tier:** The video is staged in a local temporary storage folder exposed via a public URL.
3. **Dispatch Trigger:** The local server sends a payload to the GitHub API via a Repository Dispatch event.
4. **Compute Engine Lifecycle:** A GitHub Actions container wakes up, downloads the source video, evaluates its properties, and transcodes it using FFmpeg.
5. **Dynamic Tier Guardrail:** The script analyzes the source file's vertical pixel resolution. It automatically processes only equal or lower-resolution target streaming files, completely preventing wasteful upscaling.
6. **CDN Synchronization:** `rclone` uses maximized concurrent pipelines (`--transfers 16`, `--checkers 32`) to sync the media directory layout directly to Cloudflare R2.
7. **Callback Closure:** GitHub targets a webhook on the local server to report completion time benchmarks and clean up local media buffers.

---

## 💾 Core Infrastructure Code

### 1. GitHub Actions Pipeline File (`.github/workflows/encode.yml`)

```yaml
name: Distributed HLS Cluster Encoder

on:
  repository_dispatch:
    types: [trigger-encode]

jobs:
  build-and-transcode:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Codebase
        uses: actions/checkout@v4

      - name: Setup Node Environment
        uses: actions/setup-node@v4
        with:
          node-version: 20

      - name: Install System Dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y ffmpeg
          sudo curl [https://rclone.org/install.sh](https://rclone.org/install.sh) | sudo bash

      - name: Configure Rclone Credentials
        run: |
          mkdir -p ~/.config/rclone
          cat << EOF > ~/.config/rclone/rclone.conf
          [r2]
          type = s3
          provider = Cloudflare
          access_key_id = ${{ secrets.R2_ACCESS_KEY_ID }}
          secret_access_key = ${{ secrets.R2_SECRET_ACCESS_KEY }}
          endpoint = ${{ secrets.R2_ENDPOINT }}
          acl = private
          EOF

      - name: Download Processing Target File
        run: |
          curl -L "${{ github.event.client_payload.video_url }}" -o input.mp4

      - name: Run Dedicated Transcoder
        id: transcode
        env:
          OUTPUT_NAME: ${{ github.event.client_payload.output_name }}
        run: |
          cat << 'EOF' > run-encode.js
          const ffmpeg = require('fluent-ffmpeg');
          const fs = require('fs');
          const path = require('path');
          
          const input = 'input.mp4';
          const outDir = './output/media';
          fs.mkdirSync(outDir, { recursive: true });

          ffmpeg.ffprobe(input, (err, metadata) => {
            if (err) { console.error(err); process.exit(1); }
            
            const videoStream = metadata.streams.find(s => s.codec_type === 'video');
            const nativeHeight = videoStream.height;
            const duration = metadata.format.duration;
            
            console.log(`Detected source video height: ${nativeHeight}p`);
            
            const randomTime = Math.floor(Math.random() * (duration * 0.8)) + (duration * 0.1);
            ffmpeg(input).screenshots({
              timestamps: [randomTime],
              filename: 'thumbnail.jpg',
              folder: './output',
              size: nativeHeight >= 1080 ? '1920x1080' : '1280x720'
            }).on('end', () => {
              
              const command = ffmpeg(input);
              const activeTiers = [];
              const tiersConfig = [
                { maxTarget: 480, res: '854x480', vBit: '800k', name: '480p' },
                { maxTarget: 720, res: '1280x720', vBit: '2800k', name: '720p' },
                { maxTarget: 1080, res: '1920x1080', vBit: '5000k', name: '1080p' },
                { maxTarget: 2160, res: '3840x2160', vBit: '12000k', name: '4K' }
              ];

              tiersConfig.forEach(tier => {
                if (nativeHeight >= tier.maxTarget) {
                  console.log(`Configuring encoding stream for: ${tier.name}`);
                  command.output(path.join(outDir, `${tier.name}.m3u8`))
                    .videoCodec('libx264')
                    .audioCodec('aac')
                    .size(tier.res)
                    .videoBitrate(tier.vBit)
                    .addOptions([
                      '-preset veryfast', 
                      '-g 60', 
                      '-hls_time 6', 
                      '-hls_playlist_type vod', 
                      `-hls_segment_filename ${outDir}/${tier.name}_%03d.ts`
                    ]);
                  activeTiers.push(tier);
                }
              });

              if (activeTiers.length === 0) {
                command.output(path.join(outDir, 'native.m3u8'))
                  .videoCodec('libx264').audioCodec('aac')
                  .addOptions(['-preset veryfast', '-g 60', '-hls_time 6', '-hls_playlist_type vod', `-hls_segment_filename ${outDir}/native_%03d.ts`]);
                activeTiers.push({ res: `Native(${nativeHeight}p)`, vBit: '500k', name: 'native' });
              }

              command.on('progress', (p) => console.log(`PROGRESS_MARKER:${p.percent ? p.percent.toFixed(0) : 0}`))
              .on('end', () => {
                let master = `#EXTM3U\n#EXT-X-VERSION:3\n`;
                activeTiers.forEach(t => {
                  master += `#EXT-X-STREAM-INF:BANDWIDTH=${parseInt(t.vBit) * 1000},RESOLUTION=${t.res}\nmedia/${t.name}.m3u8\n`;
                });
                fs.writeFileSync('./output/master.m3u8', master);
                console.log("TRANSCODE_SUCCESSFUL");
              }).on('error', (err) => { console.error(err); process.exit(1); }).run();
            });
          });
          EOF
          
          START_TIME=$(date +%s)
          node run-encode.js
          END_TIME=$(date +%s)
          echo "ELAPSED_SECONDS=$((END_TIME - START_TIME))" >> $GITHUB_ENV

      - name: Deploy Assets to Cloudflare R2 via Rclone
        env:
          PARENT_FOLDER: ${{ github.event.client_payload.parent_folder }}
          OUTPUT_NAME: ${{ github.event.client_payload.output_name }}
          BUCKET: ${{ secrets.R2_BUCKET_NAME }}
        run: |
          rclone copy ./output r2:$BUCKET/$PARENT_FOLDER/$OUTPUT_NAME \
            --transfers 16 \
            --checkers 32 \
            --fast-list \
            -P

      - name: Trigger Finished Webhook callback
        if: always()
        run: |
          curl -X POST "${{ github.event.client_payload.callback_webhook }}" \
            -H "Content-Type: application/json" \
            -d '{"status": "${{ job.status }}", "output_name": "${{ github.event.client_payload.output_name }}", "time_taken_seconds": "${{ env.ELAPSED_SECONDS }}"}'