
// tiny helper so we always send the page info too
const sendGA = (name, params = {}) => {
    if (typeof window.gtag === "function") {
        window.gtag("event", name, {
            ...params,
            page_location: location.href,
            page_title: document.title,
        });
    }
};

// figure out where the CTA lives
const areaFor = (el) => {
    if (!el) return "unknown";
    if (el.closest("nav")) return "navbar";
    if (el.closest("#product")) return "hero";
    if (el.closest(".pricing")) return "pricing";
    return el.closest("section")?.id || "other";
};

const labelFor = (el) =>
    (el?.innerText || el?.value || "").trim() || "(no text)";

// Preserve the CTA that opened the modal (set in Step 1).
// If you didn't keep it global, we’ll reconstruct a minimal version.
let lastWaitlistTrigger = window.lastWaitlistTrigger || null;

// 1) track clicks on any "Request Access" opener
document.querySelectorAll(".join-waitlist-btn").forEach((btn) => {
    if (btn.dataset.gaBound) return; // avoid double binding
    btn.dataset.gaBound = "1";

    btn.addEventListener(
        "click",
        () => {
            const watchedDemo = sessionStorage.getItem("watched_demo") === "1";
            const clickedLogin = sessionStorage.getItem("clicked_login") === "1"; // clickedLogin

            const info = {
                cta_text: labelFor(btn),
                cta_area: areaFor(btn),
                cta_id: btn.id || null,
                watched_demo_before: watchedDemo ? "yes" : "no",
                clicked_login_before: clickedLogin ? "yes" : "no",
            };

            // keep for the modal attribution
            lastWaitlistTrigger = info;
            window.lastWaitlistTrigger = info;

            sendGA("try_beta_click", info);
        },
        {capture: true}
    );
});

// 2) when the modal actually opens, log it and attach the source CTA
const modalEl = document.getElementById("waitlistModal");
if (modalEl) {
    modalEl.addEventListener("shown.bs.modal", () => {
        sendGA("waitlist_modal_open", {...lastWaitlistTrigger});
    });
}

// ── modal instrumentation ───────────────────────────────────
const submitBtn = document.getElementById("submitBtn");
const formEl = document.getElementById("brebaWaitlistForm");


// Track open time & close reason
let shownAt = 0;
let closeReason = "unknown";

if (modalEl) {
    // When shown
    modalEl.addEventListener("shown.bs.modal", () => {
        shownAt = Date.now();
        closeReason = "unknown";
        // if Step 1 populated window.lastWaitlistTrigger, bring it in
        lastWaitlistTrigger = window.lastWaitlistTrigger || lastWaitlistTrigger || {};
        // (Step 1 already sends waitlist_modal_open)
    });

    // Close by clicking the (X) button
    const xBtn = modalEl.querySelector(".btn-close");
    if (xBtn) {
        xBtn.addEventListener("click", () => {
            closeReason = "close_button";
        }, {capture: true});
    }

    // Close by backdrop click
    modalEl.addEventListener("mousedown", (e) => {
        if (e.target === modalEl) {
            closeReason = "backdrop_click";
        }
    }, {capture: true});

    // Close by ESC
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && modalEl.classList.contains("show")) {
            closeReason = "esc_key";
        }
    });

    // When fully hidden, send one unified close event
    modalEl.addEventListener("hidden.bs.modal", () => {
        const timeOpenMs = shownAt ? (Date.now() - shownAt) : null;
        sendGA("waitlist_modal_close", {
            close_reason: closeReason,
            time_open_ms: timeOpenMs,
            ...lastWaitlistTrigger,
        });
        shownAt = 0;
        closeReason = "unknown";
    });
}

// ── interactions INSIDE the modal ───────────────────────────
if (submitBtn) {
    // Click on Submit button
    submitBtn.addEventListener("click", () => {
        const clickedLogin = sessionStorage.getItem("clicked_login") === "1"; // clickedLogin
        const watchedDemo = sessionStorage.getItem("watched_demo") === "1";

        sendGA("waitlist_submit_click", {
            button_text: labelFor(submitBtn),
            button_area: "waitlist_modal",
            watched_demo_before: watchedDemo ? "yes" : "no",
            clicked_login_before: clickedLogin ? "yes" : "no",
        });
    }, {capture: true});
}

if (formEl) {
    formEl.addEventListener("submit", () => {
        const watchedDemo = sessionStorage.getItem("watched_demo") === "1";
        sendGA("waitlist_submit_completed", {
            source_area: "waitlist_modal",
            watched_demo_before: watchedDemo ? "yes" : "no",
        });
    });
}

// Track Watch Demo button clicks
const demoBtn = document.querySelector('.hero-actions a.btn-secondary');
if (demoBtn) {
    demoBtn.addEventListener('click', () => {
        sendGA('watch_demo_click', {
            button_text: demoBtn.innerText.trim(),
            button_area: 'hero',
            button_url: demoBtn.href
        });
        // Mark session with a flag so we know this user watched demo before Request Access
        sessionStorage.setItem('watched_demo', '1');
    }, {capture: true});
}

const loginLink = document.getElementById('loginLink');
if (loginLink) {
    loginLink.addEventListener('click', () => {
        sendGA('login_click', {
            button_text: loginLink.innerText.trim(),
            button_area: 'navbar',
            button_url: loginLink.href
        });
        sessionStorage.setItem('login_clicked', '1');
    }, {capture: true});
}