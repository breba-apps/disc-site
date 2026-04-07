// Mobile Navigation Toggle
document.addEventListener('DOMContentLoaded', function () {
    // Smooth scrolling for navigation links
    const navLinksSmooth = document.querySelectorAll('a[href^="#"]');
    navLinksSmooth.forEach(link => {
        link.addEventListener('click', function (e) {
            const targetId = this.getAttribute('href');
            // we don't want this behavior for anchor links with dummy hrefs equaling #
            // Only apply this to anchor links with hrefs that look like #pricing
            if (targetId && targetId !== "#") {
                e.preventDefault();
                const targetSection = document.querySelector(targetId);

                if (targetSection) {
                    const offsetTop = targetSection.offsetTop - 80; // Account for fixed navbar
                    window.scrollTo({
                        top: offsetTop,
                        behavior: 'smooth'
                    });
                }
            }
        });
    });

    // Copy URL functionality
    const copyButtons = document.querySelectorAll('.btn-secondary');
    copyButtons.forEach(button => {
        if (button.textContent.includes('Copy')) {
            button.addEventListener('click', function () {
                const urlText = this.previousElementSibling.textContent;
                navigator.clipboard.writeText(urlText).then(() => {
                    const originalText = this.textContent;
                    this.textContent = 'Copied!';
                    this.style.background = '#10b981';
                    this.style.color = 'white';

                    setTimeout(() => {
                        this.textContent = originalText;
                        this.style.background = '';
                        this.style.color = '';
                    }, 2000);
                });
            });
        }
    });

    // Animate elements on scroll
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('animate-in');
            }
        });
    }, observerOptions);

    // Observe elements for animation
    const animateElements = document.querySelectorAll('.feature-card, .testimonial-card, .pricing-card');
    animateElements.forEach(el => {
        observer.observe(el);
    });

    // Parallax effect for hero section
    window.addEventListener('scroll', () => {
        const scrolled = window.pageYOffset;
        const hero = document.querySelector('.hero');
        const floatingCard = document.querySelector('.floating-card');

        if (hero && floatingCard) {
            const rate = scrolled * -0.5;
            floatingCard.style.transform = `translateY(${rate}px)`;
        }
    });

    // Add loading animation
    window.addEventListener('load', () => {
        document.body.classList.add('loaded');
    });
});

// Add some interactive hover effects
document.addEventListener('DOMContentLoaded', function () {
    // Add hover effects to cards
    const cards = document.querySelectorAll('.feature-card, .testimonial-card, .pricing-card');
    cards.forEach(card => {
        card.addEventListener('mouseenter', function () {
            this.style.transform = 'translateY(-10px) scale(1.02)';
        });

        card.addEventListener('mouseleave', function () {
            this.style.transform = 'translateY(0) scale(1)';
        });
    });

    // typing effect
    const line1El = document.getElementById('heroLine1');
    const line2El = document.getElementById('heroLine2');

    if (line1El && line2El) {
        const line1 = 'Your landing page';
        const line2 = 'without the struggle';

        let i = 0;
        const step = () => {
            if (i < line1.length) {
                line1El.textContent = line1.slice(0, ++i);
            } else if (i - line1.length < line2.length) {
                line2El.textContent = line2.slice(0, i++ - line1.length + 1);
            } else {
                return;
            }
            setTimeout(step, 50);
        };
        setTimeout(step, 500);
    }
});


// Home page specific functionality
if (document.getElementById('brebaWaitlistForm')) {
    // Waitlist Modal logic
    function openWaitlistModal() {
        var waitlistModal = new bootstrap.Modal(document.getElementById('waitlistModal'));
        waitlistModal.show();
    }

    document.querySelectorAll('.join-waitlist-btn').forEach(btn => {
        btn.addEventListener('click', openWaitlistModal);
    });

    // Optional: Close modal on ESC
    document.addEventListener('keydown', function (e) {
        if (e.key === "Escape") {
            var modalEl = document.getElementById('waitlistModal');
            if (modalEl && modalEl.classList.contains('show')) {
                bootstrap.Modal.getInstance(modalEl).hide();
            }
        }
    });

    // Waitlist form submission
    document.getElementById("brebaWaitlistForm").addEventListener("submit", async function (e) {
        e.preventDefault();

        const form = e.target;
        const data = {
            email: form.email.value,
            alphaAccess: form.alphaAccess?.value || "",
            privateCloud: form.privateCloud?.value || "",
            comments: form.comments.value
        };

        const alertBox = document.getElementById("formAlert");
        const submitBtn = document.getElementById("submitBtn");
        const spinner = document.getElementById("submitSpinner");
        const submitText = document.getElementById("submitText");

        alertBox.classList.add("d-none");
        spinner.classList.remove("d-none");
        submitText.textContent = "Submitting...";

        try {
            const response = await fetch("https://script.google.com/macros/s/AKfycbwCbKjWjO4ZkDWzFCeh7zo7e1rnHu6OP-ydwlJVJRyp-AjGav1gaG_5N1yEzOArvklW/exec", {
                redirect: "follow",
                method: "POST",
                headers: {
                    "Content-Type": "text/plain;charset=utf-8",
                },
                body: JSON.stringify(data)
            });
            const text = await response.text();
            if (!response.ok) throw new Error(text);

            form.reset();
            alertBox.className = "alert alert-success";
            alertBox.textContent = "🎉 Thank you! We are currently at capacity for the beta, but we will onboard you as soon as possible.";
            alertBox.classList.remove("d-none");

            // Wait 1.5s then close modal
            setTimeout(() => {
                const modal = bootstrap.Modal.getInstance(document.getElementById("waitlistModal"));
                modal.hide();
                alertBox.classList.add("d-none"); // hide alert after closing
            }, 5000);

        } catch (error) {
            alertBox.className = "alert alert-danger";
            alertBox.textContent = "❌ There was an error submitting the form. Please try again.";
            alertBox.classList.remove("d-none");
            console.error("Submission failed", error);
        }

        spinner.classList.add("d-none");
        submitText.textContent = "Submit";
    });

    // Modal focus
    document.getElementById('waitlistModal').addEventListener('shown.bs.modal', function () {
        const emailInput = document.querySelector('#waitlistModal input[name="email"]');
        if (emailInput) {
            emailInput.focus();
        }
    });

    // Demo modal
    const modal = document.getElementById('demoModal');
    const frame = document.getElementById('demoVideo');

    // When the trigger is clicked, set the iframe src (with autoplay)
    document.querySelectorAll('[data-bs-target="#demoModal"]').forEach(el => {
        el.addEventListener('click', function () {
            const url = this.getAttribute('data-video')
                || 'https://www.youtube.com/embed/Txv-lUdk1LM?rel=0&autoplay=1&rel=0';
            frame.src = url;
        });
    });

    // When modal closes, stop the video by clearing src
    modal.addEventListener('hidden.bs.modal', function () {
        frame.src = '';
    });
}

document.querySelectorAll('a[href*="/chainlit/auth/oauth/"]').forEach((a) => {
    a.addEventListener("click", () => {
        const spinner = a.querySelector(".spinner-border");
        const label = a.querySelector(".oauth-label");
        const img = a.querySelector("img")
        const i = a.querySelector("i")

        let old_text = ""
        if (spinner) spinner.classList.remove("d-none");
        if (img) img.classList.add("d-none");
        if (i) i.classList.add("d-none");
        if (label) {
            old_text = label.textContent;
            label.textContent = "Loading…";
        }
        setTimeout(() => {
            if (spinner) spinner.classList.add("d-none");
            if (img) img.classList.remove("d-none");
            if (i) i.classList.remove("d-none");
            if (label) label.textContent = old_text;
        }, 1000)
    });
});
