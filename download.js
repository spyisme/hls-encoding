function getGDriveLinkId(fileId) {
    if (fileId.includes('drive.google.com')) {
        const match = fileId.match(/\/d\/([^/]+)/) || fileId.match(/id=([^&]+)/);
        return match ? match[1] : fileId;
    }
    return fileId;
}

function formatBytes(bytes) {
    if (isNaN(bytes) || bytes <= 0) return null;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${parseFloat((bytes / Math.pow(1024, i)).toFixed(2))} ${sizes[i]}`;
}

async function CustomDriveAudit(fileId) {
    const id = getGDriveLinkId(fileId);
    const downloadUrl = `https://drive.google.com/uc?export=download&id=${id}`;
    
    try {
        let cookies = [];
        const headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.8'
        };

        // Hop 1: Initial Handshake
        const response = await fetch(downloadUrl, { method: 'GET', headers, redirect: 'manual' });
        
        const setCookieHeader = response.headers.get('set-cookie');
        if (setCookieHeader) {
            cookies = setCookieHeader.split(/,(?=[^;]*=)/).map(c => c.split(';')[0].trim());
        }

        const redirectUrl = response.headers.get('location') || '';
        if (redirectUrl.includes('ServiceLogin') || redirectUrl.includes('accounts.google.com')) {
            return { id, name: 'Private Asset', size: 'Locked', sizeFound: false };
        }

        // Hop 2: Session Validation
        if (cookies.length > 0) {
            headers['Cookie'] = cookies.join('; ');
        }
        
        const nextTarget = redirectUrl || downloadUrl;
        const finalResponse = await fetch(nextTarget, { method: 'GET', headers });
        const contentType = finalResponse.headers.get('content-type') || '';
        const htmlBody = await finalResponse.text();

        // Standard private/deleted block
        if (htmlBody.includes('You need access') || htmlBody.includes('Request access') || htmlBody.includes('item-not-found-page')) {
            return { id, name: 'Hidden File', size: 'Locked', sizeFound: false };
        }

        let fileName = 'Unknown File';

        // CONDITION 1: It hit the HTML Virus Screen (Large File)
        if (contentType.includes('text/html') && (htmlBody.includes('Virus scan warning') || htmlBody.includes('uc-main'))) {
            let extractedSize = null;
            
            const textBlockMatch = htmlBody.match(/<span class="uc-name-size">([\s\S]*?)<\/span>/);
            if (textBlockMatch) {
                const innerHtml = textBlockMatch[1];
                
                const nameMatch = innerHtml.match(/>([^<]+)<\/a>/);
                if (nameMatch) fileName = nameMatch[1].trim();
                
                const sizeMatch = innerHtml.match(/\(([^)]+)\)/);
                if (sizeMatch) extractedSize = sizeMatch[1].trim();
            }

            if (fileName === 'Unknown File') {
                const titleMatch = htmlBody.match(/<title>([^<]+)<\/title>/);
                if (titleMatch) fileName = titleMatch[1].replace(' - Google Drive', '').trim();
            }

            if (extractedSize) {
                return { id, name: fileName, size: extractedSize, sizeFound: true };
            } else {
                return { id, name: fileName, size: 'Unknown Size', sizeFound: false };
            }
        }

        // CONDITION 2: It is a small file (Direct Binary Payload)
        const contentLengthHeader = finalResponse.headers.get('content-length');
        const calculatedSize = contentLengthHeader ? formatBytes(parseInt(contentLengthHeader, 10)) : null;

        const titleMatch = htmlBody.match(/<title>([^<]+)<\/title>/);
        if (titleMatch) fileName = titleMatch[1].replace(' - Google Drive', '').trim();

        if (calculatedSize) {
            return { id, name: fileName, size: calculatedSize, sizeFound: true };
        } else {
            return { id, name: fileName, size: 'Unknown Size', sizeFound: false };
        }

    } catch (error) {
        return { id, name: 'Error Context', size: 'Unknown', sizeFound: false };
    }
}

// ==========================================
// MODULE EXPORTS
// ==========================================
module.exports = { CustomDriveAudit, getGDriveLinkId, formatBytes };

// ==========================================
// RUN THE CUSTOM CONFIGURATION (CLI only)
// ==========================================
if (require.main === module) {
    const FILE_ID = 'https://drive.google.com/file/d/1qOy-zZ-fQ9quYQ3rRdcEKkyYzjKSWcZI/view?usp=drive_link'; 

    CustomDriveAudit(FILE_ID).then((result) => {
        console.log('\n--- CUSTOM PERMISSION MATRIX ---');
        console.log(`FILE NAME:  ${result.name}`);
        console.log(`SIZE:       ${result.size}`);
        console.log(`SIZE FOUND: ${result.sizeFound}`);
        console.log(`FILE ID:    ${result.id}\n`);
        process.exit(0);
    });
}