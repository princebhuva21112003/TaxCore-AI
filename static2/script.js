const canvas = document.getElementById('networkCanvas');
const ctx = canvas.getContext('2d');
let width, height, centerX, centerY;

// --- Camera & View State ---
let viewState = 'main';
let activeCategory = null;
let globalAlpha = 1.0;
let transitioning = false;

let camera = { x: 0, y: 0, zoom: 1 };

// --- CA Database ---
const categories = [
    { id: 'CA BRAIN', sub: 'MAIN DATABASE', color: 'var(--cat-blue)', hex: '#38bdf8' },
    { id: 'AUDITING', sub: 'Ledger - Fraud AI - Reconciliation', color: 'var(--cat-green)', hex: '#34d399' },
    { id: 'COMPLIANCE', sub: 'ROC - MCA - Notice Resolver', color: 'var(--cat-purple)', hex: '#a78bfa' },
    { id: 'BOOKKEEPING', sub: 'OCR Invoices - Bank Sync - ERP', color: 'var(--cat-amber)', hex: '#f59e0b' },
    { id: 'ADVISORY', sub: 'Tax Optimization - RAG Bot', color: 'var(--cat-pink)', hex: '#f472b6' },
    { id: 'CA SIGNATURE', sub: 'One-Click CA Review & Attestation', color: 'var(--cat-cyan)', hex: '#06b6d4' }
];

const treeData = {
    "CA BRAIN":
        [
            {
                id: "T1",
                label: "Financial Reporting",
                icon: "📊",
                desc: "AI-driven Ind AS compliance pipeline, intelligent consolidation of multi-entity financial statements, and automated variance analysis."
            },
            {
                id: "T2",
                label: "Advanced Financial Management",
                icon: "📈",
                desc: "Algorithmic portfolio optimization, automated forex risk hedging, and machine learning-powered cash flow forecasting models."
            },
            {
                id: "T3",
                label: "Advanced Auditing, Assurance and Professional Ethics",
                icon: "🔍",
                desc: "LLM-based anomaly detection in ledger entries, automated substantive testing, and continuous compliance and risk monitoring."
            },
            {
                id: "T4",
                label: "Direct Tax Laws & International Taxation",
                icon: "🏛️",
                desc: "Intelligent Form 26AS/AIS parsing, automated transfer pricing analysis, and deduction maximization agent choosing the optimal tax regime."
            },
            {
                id: "T5",
                label: "Indirect Tax Laws",
                icon: "🧾",
                desc: "Agentic pipeline for GSTR-1 & 3B calculation, automated E-way bill generation, and smart reconciliation of GSTR-2B vs Purchase Register."
            },
            {
                id: "T6",
                label: "Integrated Business Solution",
                icon: "🧩",
                desc: "Multi-agent orchestration cross-referencing tax, audit, and financial data to generate holistic business strategies and boardroom-ready reports."
            }
        ],
    "AUDITING": [
        { id: "A1", label: "Deep Ledger Audit", icon: "🔍", desc: "RAG agent verifying line items against bank feeds to flag unmatched transactions." },
        { id: "A2", label: "Fraud & Anomaly Bot", icon: "🚨", desc: "Machine learning scanning for duplicate claims, fake GSTIN vendors, and circular trading." },
        { id: "A3", label: "Trial Balance AI", icon: "⚖️", desc: "Automated debit-credit balancer with adjustment entry recommendations." }
    ],
    "COMPLIANCE": [
        { id: "C1", label: "ROC & MCA Bot", icon: "🏛️", desc: "Automated filing for annual returns (MGT-7, AOC-4) and board resolution generation." },
        { id: "C2", label: "Notice Resolver RAG", icon: "📩", desc: "Upload Income Tax or GST notices; RAG agent drafts legally grounded reply letters." },
        { id: "C3", label: "Immutable Audit Log", icon: "📜", desc: "100% compliant tamper-proof audit trail tracking all AI financial adjustments." }
    ],
    "BOOKKEEPING": [
        { id: "B1", label: "OCR Receipt Parser", icon: "📷", desc: "Vision AI extracting line items, GST numbers, and vendor data from paper bills." },
        { id: "B2", label: "E-Invoicing API", icon: "💡", desc: "Instant IRN generation and E-Way bill creation directly linked with GST portal." },
        { id: "B3", label: "Bank Statement Sync", icon: "🏦", desc: "Open banking integration for instant transaction categorisation and reconciliation." }
    ],
    "ADVISORY": [
        { id: "AD1", label: "Tax Saving Advisory", icon: "💡", desc: "Conversational RAG AI offering customized legal strategies to lower annual tax liabilities." },
        { id: "AD2", label: "Cashflow Health Score", icon: "📊", desc: "Real-time liquidity, solvency, and expense analytics updated daily." }
    ],
    "CA SIGNATURE": [
        { id: "S1", label: "CA Review Bridge", icon: "✍️", desc: "Packages all audited metrics into a clean dossier for human CA digital signature." },
        { id: "S2", label: "Audit Attestation", icon: "🛡️", desc: "Verifies that AI models kept 100% statutory compliance before final approval." }
    ],
    "DEFAULT": [
        { id: "D1", label: "Automated Module", icon: "📄", desc: "Autonomous agent handling end-to-end accounting processes." }
    ]
};

let backgroundStars = [];
let mainNodes = [], mainLinks = [];
let treeNodes = [], treeLinks = [], treeArcs = [];
let dataParticles = [];

let mouse = { x: 0, y: 0, hoverNode: null };
window.addEventListener('mousemove', (e) => { mouse.x = e.clientX; mouse.y = e.clientY; });

window.addEventListener('click', () => {
    if (transitioning) return;
    if (viewState === 'main' && mouse.hoverNode && mouse.hoverNode.type === 'category') {
        startZoomTransition(mouse.hoverNode);
    } else if (viewState === 'tree' && mouse.hoverNode && mouse.hoverNode.type === 'treeChild') {
        openModal(mouse.hoverNode.label, mouse.hoverNode.desc);
    }
});

function resize() {
    width = window.innerWidth; height = window.innerHeight;
    canvas.width = width; canvas.height = height;
    centerX = width / 2; centerY = height / 2;
    buildMainGraph();
    if (viewState === 'tree') buildTreeGraph(activeCategory);
}
window.addEventListener('resize', resize);

// --- Transitions & Animations ---

// Deep Zoom Animation into a node
function startZoomTransition(node) {
    transitioning = true;
    let startZoom = camera.zoom;
    let targetZoom = 5; // How deep the zoom goes
    let duration = 900;
    let startTime = performance.now();
    let startCamX = camera.x;
    let startCamY = camera.y;

    function animateZoom(time) {
        let elapsed = time - startTime;
        let t = Math.min(elapsed / duration, 1);

        // Cubic ease-in-out for smooth camera movement
        let ease = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

        camera.zoom = startZoom + (targetZoom - startZoom) * ease;

        // Dynamically track the node as it orbits
        let currentTargetX = node.x - centerX;
        let currentTargetY = node.y - centerY;

        camera.x = startCamX + (currentTargetX - startCamX) * ease;
        camera.y = startCamY + (currentTargetY - startCamY) * ease;

        // Crossfade alpha during the second half of the zoom
        if (t > 0.5) {
            globalAlpha = Math.max(0, 1 - ((t - 0.5) * 2));
        }

        if (t < 1) {
            requestAnimationFrame(animateZoom);
        } else {
            // Zoom complete, trigger tree view
            globalAlpha = 0;
            viewState = 'tree';
            activeCategory = node.label;
            buildTreeGraph(activeCategory);

            // Reset camera for tree view
            camera.x = 0;
            camera.y = 0;
            camera.zoom = 1;

            document.getElementById('backBtn').style.display = 'flex';
            document.getElementById('sideLeft').style.display = 'block';
            document.getElementById('sideRight').style.display = 'block';
            dataParticles = [];

            fadeIn(600);
        }
    }
    requestAnimationFrame(animateZoom);
}

// Standard Fade In
function fadeIn(duration = 500) {
    let fadeStartTime = performance.now();
    function animateFade(time) {
        let elapsed = time - fadeStartTime;
        let t = Math.min(elapsed / duration, 1);
        globalAlpha = t;
        if (t < 1) {
            requestAnimationFrame(animateFade);
        } else {
            transitioning = false;
        }
    }
    requestAnimationFrame(animateFade);
}

// Standard Back Fade (Used for "Back" button)
function setState(newState) {
    if (newState === viewState || transitioning) return;
    transitioning = true;

    let startAlpha = globalAlpha;
    let fadeOutTime = performance.now();

    function animateBack(time) {
        let elapsed = time - fadeOutTime;
        let t = Math.min(elapsed / 400, 1);
        globalAlpha = startAlpha * (1 - t);

        if (t < 1) {
            requestAnimationFrame(animateBack);
        } else {
            viewState = newState;
            if (newState === 'main') {
                document.getElementById('backBtn').style.display = 'none';
                document.getElementById('sideLeft').style.display = 'none';
                document.getElementById('sideRight').style.display = 'none';
                camera.zoom = 1;
                camera.x = 0;
                camera.y = 0;
            }
            fadeIn(500);
        }
    }
    requestAnimationFrame(animateBack);
}

function openModal(title, desc) {
    document.getElementById('modalTitle').innerText = title;
    document.getElementById('modalDesc').innerText = desc;
    document.getElementById('detailModal').classList.add('active');
}
function closeModal() {
    document.getElementById('detailModal').classList.remove('active');
}

// --- Build Main Constellation Map (Zoomed Out Layout) ---
function buildMainGraph() {
    mainNodes = []; mainLinks = [];
    const coreNodes = [];

    for (let i = 0; i < 60; i++) {
        let angle = Math.random() * Math.PI * 2;
        let dist = Math.random() * 35; // slightly wider core
        let c = categories[Math.floor(Math.random() * categories.length)].hex;
        let node = {
            id: 'core_' + i, type: 'core', groupId: 'core',
            baseX: Math.cos(angle) * dist, baseY: Math.sin(angle) * dist,
            color: c, radius: Math.random() * 1.5 + 1.0, speed: Math.random() * 0.015
        };
        mainNodes.push(node);
        coreNodes.push(node);
    }
    for (let i = 0; i < 30; i++) {
        mainLinks.push({
            source: coreNodes[Math.floor(Math.random() * coreNodes.length)],
            target: coreNodes[Math.floor(Math.random() * coreNodes.length)],
            color: 'rgba(255,255,255,0.05)', isCore: true
        });
    }

    // Increased radius sizes for a "zoomed in" initial look
    const radiusCategory = Math.min(width, height) * 0.30;
    const angleStep = (Math.PI * 2) / categories.length;

    categories.forEach((cat, index) => {
        let initialAngle = index * angleStep - (Math.PI / 2);
        let groupId = 'cat_' + index;

        let catNode = {
            id: groupId, groupId: groupId, type: 'category', label: cat.id, sub: cat.sub, color: cat.hex,
            angleOffset: initialAngle, orbitRadius: radiusCategory,
            radius: 20, hoverRadius: 26, targetOpacity: 1.0, currentOpacity: 1.0
        };
        mainNodes.push(catNode);

        mainLinks.push({ source: coreNodes[Math.floor(Math.random() * coreNodes.length)], target: catNode, color: 'rgba(255,255,255,0.15)', isCore: false });

        let numBranches = 3 + Math.floor(Math.random() * 2);
        let branchSpread = 0.5;

        for (let b = 0; b < numBranches; b++) {
            let bAngleOffset = initialAngle + (b - (numBranches - 1) / 2) * (branchSpread / numBranches);
            let bDist = radiusCategory + 60 + Math.random() * 25; // pushed further out

            let branchNode = {
                id: `branch_${index}_${b}`, groupId: groupId, type: 'branch', parent: catNode,
                angleOffset: bAngleOffset, orbitRadius: bDist,
                color: cat.hex, radius: 2.5, isOutline: true,
                targetOpacity: 1.0, currentOpacity: 1.0
            };
            mainNodes.push(branchNode);
            mainLinks.push({ source: catNode, target: branchNode, color: 'rgba(255,255,255,0.15)', isCore: false });

            let numLeaves = 1 + Math.floor(Math.random() * 3);
            let leafSpread = 0.25;

            for (let l = 0; l < numLeaves; l++) {
                let lAngleOffset = bAngleOffset + (l - (numLeaves - 1) / 2) * (leafSpread / (numLeaves || 1));
                lAngleOffset += (Math.random() - 0.5) * 0.08;
                let lDist = bDist + 40 + Math.random() * 25; // pushed further out

                let leafNode = {
                    id: `leaf_${index}_${b}_${l}`, groupId: groupId, type: 'leaf', parent: branchNode,
                    angleOffset: lAngleOffset, orbitRadius: lDist,
                    color: Math.random() > 0.3 ? '#ffffff' : cat.hex, radius: 1.8, isOutline: Math.random() > 0.5,
                    targetOpacity: 1.0, currentOpacity: 1.0
                };
                mainNodes.push(leafNode);
                mainLinks.push({ source: branchNode, target: leafNode, color: 'rgba(255,255,255,0.1)', isCore: false });
            }
        }
    });
}

// --- Build Radial Tree Map ---
function buildTreeGraph(category) {
    treeNodes = []; treeLinks = []; treeArcs = [];

    let rootNode = {
        id: 'treeRoot', type: 'treeRoot', label: category, sub: "automated agent pipelines",
        x: centerX, y: height - 100, radius: 24, color: '#f59e0b'
    };
    treeNodes.push(rootNode);

    let arcRadii = [height * 0.35, height * 0.55];
    arcRadii.forEach(r => treeArcs.push({ x: rootNode.x, y: rootNode.y, radius: r }));

    let items = treeData[category] || treeData["DEFAULT"];
    let numItems = items.length;
    let angleStart = Math.PI * 1.15;
    let angleEnd = Math.PI * 1.85;
    let angleStep = (angleEnd - angleStart) / (numItems - 1 || 1);

    items.forEach((item, i) => {
        let angle = angleStart + (i * angleStep);
        let rDist = (i % 2 === 0) ? arcRadii[0] : arcRadii[1];
        let nx = rootNode.x + Math.cos(angle) * rDist;
        let ny = rootNode.y + Math.sin(angle) * rDist;

        let childNode = {
            id: item.id, type: 'treeChild', label: item.label, icon: item.icon, desc: item.desc,
            x: nx, y: ny, radius: 22, hoverRadius: 26, color: '#f8fafc'
        };
        treeNodes.push(childNode);
        treeLinks.push({ source: rootNode, target: childNode, color: 'rgba(255,255,255,0.2)' });

        let numSubs = 1 + Math.floor(Math.random() * 2);
        for (let s = 0; s < numSubs; s++) {
            let subAngle = angle + (Math.random() - 0.5) * 0.4;
            let subRadius = rDist + 55;
            let snx = rootNode.x + Math.cos(subAngle) * subRadius;
            let sny = rootNode.y + Math.sin(subAngle) * subRadius;

            let subNode = {
                id: `sub_${i}_${s}`, type: 'treeDeco',
                x: snx, y: sny, radius: 3, color: 'transparent', outline: '#64748b'
            };
            treeNodes.push(subNode);
            treeLinks.push({ source: childNode, target: subNode, color: 'rgba(255,255,255,0.15)' });
        }
    });
}

for (let i = 0; i < 400; i++) {
    backgroundStars.push({
        x: Math.random() * window.innerWidth, y: Math.random() * window.innerHeight,
        radius: Math.random() * 1.5, opacity: Math.random() * 0.6 + 0.1
    });
}
resize();

let globalTime = 0;
const ORBIT_SPEED = 0.0003;

function animate() {
    ctx.clearRect(0, 0, width, height);
    ctx.globalAlpha = globalAlpha;
    globalTime += 1;
    mouse.hoverNode = null;

    // Draw Stars (Rendered independently of camera bounds to prevent huge scaling)
    backgroundStars.forEach(star => {
        ctx.beginPath(); ctx.arc(star.x, star.y, star.radius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 255, 255, ${star.opacity})`; ctx.fill();
    });

    // Camera Viewport Setup
    ctx.save();
    ctx.translate(centerX, centerY);
    ctx.scale(camera.zoom, camera.zoom);
    ctx.translate(-centerX - camera.x, -centerY - camera.y);

    // Translate physical mouse to World Mouse Space based on camera zoom/pan
    let worldMouseX = (mouse.x - centerX) / camera.zoom + centerX + camera.x;
    let worldMouseY = (mouse.y - centerY) / camera.zoom + centerY + camera.y;

    if (viewState === 'main') {
        let mouseOffsetX = (mouse.x - centerX) * 0.02;
        let mouseOffsetY = (mouse.y - centerY) * 0.02;

        let activeGroupId = null;
        // Detect Hover in World Space
        mainNodes.forEach(node => {
            if (node.type !== 'core') {
                let dx = worldMouseX - node.x, dy = worldMouseY - node.y;
                let r = node.type === 'category' ? node.hoverRadius : node.radius * 3;
                if (Math.sqrt(dx * dx + dy * dy) < r) {
                    mouse.hoverNode = node;
                    activeGroupId = node.groupId;
                }
            }
        });

        mainNodes.forEach(node => {
            if (node.type === 'core') return;
            if (activeGroupId === null) {
                node.targetOpacity = 1.0;
            } else {
                node.targetOpacity = (node.groupId === activeGroupId) ? 1.0 : 0.15;
            }
            node.currentOpacity += (node.targetOpacity - node.currentOpacity) * 0.1;
        });

        mainNodes.forEach(node => {
            if (node.type === 'core') {
                let angle = globalTime * node.speed + parseInt(node.id.split('_')[1]);
                let dist = Math.sqrt(node.baseX * node.baseX + node.baseY * node.baseY);
                node.x = centerX + Math.cos(angle) * dist - mouseOffsetX;
                node.y = centerY + Math.sin(angle) * dist - mouseOffsetY;
            } else if (node.type === 'category' || node.type === 'branch' || node.type === 'leaf') {
                let currentAngle = node.angleOffset + (globalTime * ORBIT_SPEED);
                node.x = centerX + Math.cos(currentAngle) * node.orbitRadius - mouseOffsetX;
                node.y = centerY + Math.sin(currentAngle) * node.orbitRadius - mouseOffsetY;
            }
        });

        // Generate Data Particles
        if (Math.random() < 0.04) {
            let validLinks = mainLinks.filter(l => !l.isCore);
            if (validLinks.length > 0) {
                let link = validLinks[Math.floor(Math.random() * validLinks.length)];
                dataParticles.push({
                    source: link.source,
                    target: link.target,
                    progress: 0,
                    speed: 0.01 + Math.random() * 0.005,
                    color: link.target.color || '#ffffff'
                });
            }
        }

        // Draw Main Links
        mainLinks.forEach(link => {
            ctx.beginPath(); ctx.moveTo(link.source.x, link.source.y); ctx.lineTo(link.target.x, link.target.y);

            if (link.isCore) {
                ctx.strokeStyle = link.color;
            } else {
                let op = link.target.currentOpacity;
                let rgb = link.color.substring(0, link.color.lastIndexOf(','));
                ctx.strokeStyle = `${rgb}, ${op * 0.25})`;
            }
            ctx.lineWidth = 1; ctx.stroke();
        });

        // Draw Particles
        for (let i = dataParticles.length - 1; i >= 0; i--) {
            let p = dataParticles[i];
            p.progress += p.speed;

            if (p.progress >= 1) {
                dataParticles.splice(i, 1);
                continue;
            }

            let px = p.source.x + (p.target.x - p.source.x) * p.progress;
            let py = p.source.y + (p.target.y - p.source.y) * p.progress;

            ctx.globalAlpha = p.target.currentOpacity;
            ctx.beginPath();
            ctx.arc(px, py, 2, 0, Math.PI * 2);
            ctx.fillStyle = p.color;
            ctx.fill();
            ctx.shadowBlur = 10;
            ctx.shadowColor = p.color;
            ctx.fill();
            ctx.shadowBlur = 0;
            ctx.globalAlpha = 1.0;
        }

        // Draw Main Nodes
        mainNodes.forEach(node => {
            if (node.type !== 'core') {
                ctx.globalAlpha = node.currentOpacity;
            }

            ctx.beginPath();
            let isHovered = mouse.hoverNode === node;
            let rad = (isHovered && node.type === 'category') ? node.hoverRadius : node.radius;

            ctx.arc(node.x, node.y, rad, 0, Math.PI * 2);

            if (node.isOutline) {
                ctx.strokeStyle = node.color; ctx.lineWidth = 1.5; ctx.stroke();
            } else {
                ctx.fillStyle = node.color; ctx.fill();
            }

            if (node.type === 'category') {
                ctx.strokeStyle = 'rgba(255,255,255,0.3)';
                ctx.lineWidth = 1;
                ctx.beginPath(); ctx.arc(node.x, node.y, rad + 6, 0, Math.PI * 2); ctx.stroke();
                ctx.strokeStyle = 'rgba(255,255,255,0.1)';
                ctx.beginPath(); ctx.arc(node.x, node.y, rad + 2, 0, Math.PI * 2); ctx.stroke();

                ctx.textAlign = "center";
                let dx = node.x - centerX;
                let dy = node.y - centerY;
                let dist = Math.sqrt(dx * dx + dy * dy);
                let pushFactor = 45;

                let textX = node.x + (dx / dist) * pushFactor;
                let textY = node.y + (dy / dist) * pushFactor;

                ctx.font = "600 12px 'Cinzel', serif";
                ctx.fillStyle = isHovered ? node.color : "#ffffff";
                ctx.letterSpacing = "2px";
                ctx.fillText(node.label, textX, textY);

                ctx.font = "400 9px 'Inter', sans-serif";
                ctx.fillStyle = "rgba(255, 255, 255, 0.4)";
                ctx.fillText(node.sub, textX, textY + 14);
            }
            ctx.globalAlpha = 1.0;
        });
    }

    if (viewState === 'tree') {
        treeArcs.forEach(arc => {
            ctx.beginPath(); ctx.arc(arc.x, arc.y, arc.radius, Math.PI * 1.05, Math.PI * 1.95);
            ctx.strokeStyle = 'rgba(255,255,255,0.04)'; ctx.lineWidth = 1; ctx.stroke();
        });

        treeLinks.forEach(link => {
            ctx.beginPath(); ctx.moveTo(link.source.x, link.source.y); ctx.lineTo(link.target.x, link.target.y);
            ctx.strokeStyle = link.color; ctx.lineWidth = 1; ctx.stroke();
        });

        treeNodes.forEach(node => {
            if (node.type === 'treeChild') {
                let dx = worldMouseX - node.x, dy = worldMouseY - node.y;
                if (Math.sqrt(dx * dx + dy * dy) < node.hoverRadius) mouse.hoverNode = node;
            }

            let isHovered = mouse.hoverNode === node;
            let rad = isHovered ? node.hoverRadius : node.radius;

            ctx.beginPath(); ctx.arc(node.x, node.y, rad, 0, Math.PI * 2);

            if (node.type === 'treeRoot') {
                ctx.strokeStyle = node.color; ctx.lineWidth = 2; ctx.stroke();
                ctx.textAlign = "center";
                ctx.font = "600 22px 'Cinzel', serif"; ctx.fillStyle = "#ffffff"; ctx.letterSpacing = "4px";
                ctx.fillText(node.label, node.x, node.y + 60);
                ctx.font = "400 12px 'Inter', sans-serif"; ctx.fillStyle = "rgba(255,255,255,0.4)";
                ctx.fillText(node.sub, node.x, node.y + 80);

            } else if (node.type === 'treeChild') {
                ctx.fillStyle = node.color; ctx.fill();
                ctx.textAlign = "center"; ctx.textBaseline = "middle";
                ctx.font = "14px Arial"; ctx.fillStyle = "#000000";
                ctx.fillText(node.icon, node.x, node.y);

                ctx.beginPath(); ctx.arc(node.x + rad + 2, node.y - rad - 2, 4, 0, Math.PI * 2);
                ctx.fillStyle = '#f59e0b'; ctx.fill();

                ctx.textBaseline = "alphabetic";
                ctx.font = "600 11px 'Cinzel', serif"; ctx.fillStyle = isHovered ? "#f59e0b" : "rgba(255,255,255,0.7)";
                ctx.letterSpacing = "2px";
                ctx.fillText(node.label, node.x, node.y - rad - 14);

            } else if (node.type === 'treeDeco') {
                ctx.strokeStyle = node.outline; ctx.lineWidth = 1; ctx.stroke();
                ctx.beginPath(); ctx.arc(node.x, node.y, 1.5, 0, Math.PI * 2);
                ctx.fillStyle = '#f59e0b'; ctx.fill();
            }
        });
    }

    // Restore canvas transformations
    ctx.restore();

    document.body.style.cursor = mouse.hoverNode ? 'pointer' : 'crosshair';
    ctx.globalAlpha = 1.0;
    requestAnimationFrame(animate);
}
// --- Chatbot Logic ---

// Replace this with your actual FastAPI endpoint URL
const FASTAPI_URL = "http://127.0.0.1:8000/chat";

function openChat() {
    // Hide the modal
    document.getElementById('detailModal').style.display = 'none';

    // Update chat header with the module name they clicked
    const moduleName = document.getElementById('modalTitle').innerText;
    document.getElementById('chatAgentName').innerText = moduleName + " Agent";

    // Slide in the chat sidebar
    document.getElementById('chatSidebar').classList.add('active');
}

function closeChat() {
    document.getElementById('chatSidebar').classList.remove('active');
}

function handleEnter(event) {
    if (event.key === 'Enter') {
        sendMessage();
    }
}

// --- Replace your existing sendMessage function with this updated one ---
async function sendMessage() {
    const inputField = document.getElementById('userInput');
    const message = inputField.value.trim();
    if (!message) return;

    // 1. Display User Message
    appendMessage(message, 'user-message');
    inputField.value = '';

    // Cancel any ongoing AI voice speaking when user sends a new message
    window.speechSynthesis.cancel();

    // 2. Display a loading indicator
    const loadingId = appendMessage("Thinking...", 'ai-message');

    try {
        // 3. Send to FastAPI
        const response = await fetch(FASTAPI_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message })
        });

        const data = await response.json();

        // 4. Remove loading text and append actual AI response
        document.getElementById(loadingId).remove();

        const aiResponseText = data.reply || data.response;
        appendMessage(aiResponseText, 'ai-message');

        // 5. Speak the response out loud!
        speakText(aiResponseText);

    } catch (error) {
        console.error("Error connecting to FastAPI:", error);
        document.getElementById(loadingId).remove();
        appendMessage("Error: Could not connect to the agent backend.", 'ai-message');
    }
}


// --- ADVANCED CONTINUOUS VOICE AI LOGIC ---

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition;
let isSessionActive = false;
let silenceTimer = null;
const SILENCE_DELAY = 2000; // 2 seconds of silence triggers auto-send
let accumulatedSpeech = "";

// Smart Text Formatter (Fixes symbols like @)
function formatSpeechText(text) {
    // 1. Convert voice commands like "capital p" to "P" and "small r" to "r"
    text = text.replace(/\b(capital|caps|uppercase)\s+([a-zA-Z])/gi, (match, p1, p2) => p2.toUpperCase());
    text = text.replace(/\b(small|lowercase)\s+([a-zA-Z])/gi, (match, p1, p2) => p2.toLowerCase());

    // 2. Handle symbols and extensions
    return text
        .replace(/\bat the rate of\b/gi, '@')
        .replace(/\bat the rate\b/gi, '@')
        .replace(/\bdot com\b/gi, '.com')
        .replace(/\bdot in\b/gi, '.in')
        .replace(/\bdot org\b/gi, '.org')
        .replace(/\bdot\b/gi, '.')
        .replace(/\bunderscore\b/gi, '_')
        .replace(/\bdash\b/gi, '-')
        .replace(/\bhyphen\b/gi, '-')
        .replace(/\bhashtag\b/gi, '#')
        .replace(/\bhash\b/gi, '#')
        .replace(/\bpound sign\b/gi, '#')
        .replace(/\basterisk\b/gi, '*')
        .replace(/\bstar\b/gi, '*')
        .replace(/\bpercent\b/gi, '%')
        .replace(/\bampersand\b/gi, '&')
        .replace(/\bdollar sign\b/gi, '$');
}

// Stop the bot immediately if the user starts typing manually!
document.getElementById('userInput').addEventListener('input', () => {
    if (window.speechSynthesis.speaking) {
        window.speechSynthesis.cancel();
    }
});

if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onresult = async (event) => {
        clearTimeout(silenceTimer);

        let interimTranscript = '';
        accumulatedSpeech = '';

        for (let i = event.resultIndex; i < event.results.length; ++i) {
            if (event.results[i].isFinal) {
                accumulatedSpeech += event.results[i][0].transcript;
            } else {
                interimTranscript += event.results[i][0].transcript;
            }
        }

        // Apply formatting (like changing "at the rate" to "@")
        let currentText = accumulatedSpeech + interimTranscript;
        currentText = formatSpeechText(currentText);

        document.getElementById('userInput').value = currentText;

        // 1. CHECK FOR THE WORD "STOP"
        if (/\bstop\b/i.test(currentText)) {
            let finalCleanText = currentText.replace(/\bstop\b/gi, '').trim();
            document.getElementById('userInput').value = finalCleanText;

            isSessionActive = false;
            recognition.stop();
            resetMicButton();
            window.speechSynthesis.cancel(); // Stop bot if speaking

            if (finalCleanText.length > 0) {
                sendMessage(finalCleanText);
            }
            return;
        }

        // 2. DETECT PAUSE & AUTO-SEND
        silenceTimer = setTimeout(() => {
            let finalMsg = document.getElementById('userInput').value.trim();
            if (finalMsg.length > 0) {
                recognition.stop();
                document.getElementById('userInput').value = '';
                accumulatedSpeech = '';
                sendMessage(finalMsg);
            }
        }, SILENCE_DELAY);
    };

    recognition.onerror = (event) => {
        console.error('Speech recognition error', event.error);
        if (!isSessionActive) resetMicButton();
    };

    recognition.onend = () => {
        if (!isSessionActive) {
            resetMicButton();
        }
    };

} else {
    console.warn("Web Speech API is not supported in this browser.");
}

function startMicSafe() {
    try {
        if (isSessionActive) recognition.start();
    } catch (e) { }
}

function toggleRecording() {
    if (!recognition) {
        alert("Your browser doesn't support the Web Speech API.");
        return;
    }

    const micBtn = document.getElementById('micBtn');

    // INTERRUPT FEATURE: If bot is talking, clicking Mic stops it & listens immediately!
    if (window.speechSynthesis.speaking) {
        window.speechSynthesis.cancel();
        isSessionActive = true;
        accumulatedSpeech = "";
        document.getElementById('userInput').value = "";
        startMicSafe();
        micBtn.classList.add('recording');
        micBtn.innerHTML = '<i class="fas fa-stop-circle"></i>';
        return;
    }

    if (!isSessionActive) {
        isSessionActive = true;
        accumulatedSpeech = "";
        document.getElementById('userInput').value = "";
        window.speechSynthesis.cancel();

        startMicSafe();

        micBtn.classList.add('recording');
        micBtn.innerHTML = '<i class="fas fa-stop-circle"></i>';
    } else {
        isSessionActive = false;
        recognition.stop();
        resetMicButton();
        clearTimeout(silenceTimer);

        let finalMsg = document.getElementById('userInput').value.trim();
        if (finalMsg) sendMessage(finalMsg);
    }
}

function resetMicButton() {
    const micBtn = document.getElementById('micBtn');
    if (micBtn) {
        micBtn.classList.remove('recording');
        micBtn.innerHTML = '<i class="fas fa-microphone"></i>';
    }
    isSessionActive = false;
}

async function sendMessage(overrideText = null) {
    const inputField = document.getElementById('userInput');
    const message = overrideText !== null ? overrideText : inputField.value.trim();
    if (!message) return;

    appendMessage(message, 'user-message');
    if (overrideText === null) inputField.value = '';

    // Instantly stop current voice if you send a new message
    window.speechSynthesis.cancel();
    const loadingId = appendMessage("Thinking...", 'ai-message');

    try {
        const response = await fetch(FASTAPI_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message })
        });

        // 1. Remove "Thinking..." safely
        const loadingElement = document.getElementById(loadingId);
        if (loadingElement) loadingElement.remove();

        // 2. Check if the server crashed (e.g., 500 error)
        if (!response.ok) {
            throw new Error(`Server Error: ${response.status}`);
        }

        const data = await response.json();

        // 3. Display the response safely
        const aiResponseText = data.reply || data.response || "Sorry, I received an empty response from the database.";
        appendMessage(aiResponseText, 'ai-message');

        speakText(aiResponseText);

    } catch (error) {
        console.error("Backend Error:", error);
        const loadingElement = document.getElementById(loadingId);
        if (loadingElement) loadingElement.remove();

        appendMessage("⚠️ Error: Check your Uvicorn terminal! The backend failed to respond.", 'ai-message');
        startMicSafe();
    }
}

function speakText(text) {
    if (!text) {
        startMicSafe();
        return;
    }

    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-US';
    utterance.rate = 1.05;

    utterance.onend = function () {
        if (isSessionActive) {
            startMicSafe();
        }
    };

    window.speechSynthesis.speak(utterance);
}

function appendMessage(text, className) {
    const chatBox = document.getElementById('chatBox');
    const msgDiv = document.createElement('div');
    const uniqueId = 'msg-' + Date.now(); // Create unique ID for manipulating later

    msgDiv.id = uniqueId;
    msgDiv.className = `message ${className}`;
    msgDiv.innerText = text;

    chatBox.appendChild(msgDiv);

    // Auto-scroll to bottom
    chatBox.scrollTop = chatBox.scrollHeight;

    return uniqueId;
}
// Poll backend for CAPTCHA
let currentCaptchaImage = "";
let isDownloadComplete = false;

// Poll backend for CAPTCHA and Download Status
setInterval(async () => {
    try {
        // --- 1. CAPTCHA LOGIC (Keeps your browser able to solve CAPTCHAs) ---
        let res = await fetch("http://127.0.0.1:8000/check-captcha");
        let data = await res.json();

        if (data.image) {
            // Only render if it is a NEW image we haven't shown yet (prevents duplicates)
            if (data.image !== currentCaptchaImage) {
                currentCaptchaImage = data.image;
                showCaptchaUI(data.image);
            }
        } else {
            currentCaptchaImage = ""; // Reset when backend clears it
        }

        // --- 2. AUTO-QUESTION LOGIC (Triggers the Profession question when ready) ---
        if (!isDownloadComplete) {
            let statusRes = await fetch("http://127.0.0.1:8000/check-download-status");
            let statusData = await statusRes.json();

            if (statusData.status === "ready") {
                isDownloadComplete = true;
                appendMessage(statusData.message, 'ai-message');
                speakText(statusData.message);
            }
        }
    } catch (e) {
        console.error("Polling error:", e);
    }
}, 2000);

function showCaptchaUI(base64Image) {
    const chatBox = document.getElementById('chatBox');
    const msgDiv = document.createElement('div');
    msgDiv.id = "captcha-ui";
    msgDiv.className = "message ai-message captcha-container";
    msgDiv.innerHTML = `
        <p class="captcha-title">⚠️ CAPTCHA Required</p>
        <img src="data:image/png;base64,${base64Image}" class="captcha-img" />
        <div class="captcha-input-group">
            <input type="text" id="captchaInputText" placeholder="Enter characters..." autocomplete="off">
            <button onclick="submitCaptcha()">Submit</button>
        </div>
    `;
    chatBox.appendChild(msgDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

async function submitCaptcha() {
    const text = document.getElementById("captchaInputText").value.trim();
    if (!text) return;

    document.getElementById("captcha-ui").innerHTML = "<em style='color:#34d399;'>CAPTCHA submitted. Resuming automation...</em>";
    document.getElementById("captcha-ui").removeAttribute("id");

    await fetch("http://127.0.0.1:8000/submit-captcha", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text })
    });
}
animate();