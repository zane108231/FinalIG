// Auto-dismiss alerts after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });

    // Initialize all carousels
    const carousels = document.querySelectorAll('.carousel');
    carousels.forEach(carousel => {
        new bootstrap.Carousel(carousel, {
            interval: 5000,
            wrap: true
        });
    });

    // Add smooth scrolling to stories container
    const storiesContainer = document.querySelector('.stories-container');
    if (storiesContainer) {
        let isDown = false;
        let startX;
        let scrollLeft;

        storiesContainer.addEventListener('mousedown', (e) => {
            isDown = true;
            storiesContainer.style.cursor = 'grabbing';
            startX = e.pageX - storiesContainer.offsetLeft;
            scrollLeft = storiesContainer.scrollLeft;
        });

        storiesContainer.addEventListener('mouseleave', () => {
            isDown = false;
            storiesContainer.style.cursor = 'grab';
        });

        storiesContainer.addEventListener('mouseup', () => {
            isDown = false;
            storiesContainer.style.cursor = 'grab';
        });

        storiesContainer.addEventListener('mousemove', (e) => {
            if (!isDown) return;
            e.preventDefault();
            const x = e.pageX - storiesContainer.offsetLeft;
            const walk = (x - startX) * 2;
            storiesContainer.scrollLeft = scrollLeft - walk;
        });
    }

    const progressiveToggle = document.getElementById('progressiveToggle');
    if (progressiveToggle && progressiveToggle.checked) {
        progressiveLoadMedia();
    }
    if (progressiveToggle) {
        progressiveToggle.addEventListener('change', function() {
            window.location.reload();
        });
    }
});

function progressiveLoadMedia() {
    const mediaElements = document.querySelectorAll('[data-progressive]');
    mediaElements.forEach(el => {
        const url = el.getAttribute('data-url');
        const type = el.getAttribute('data-type');
        if (!url) return;
        fetch(`/media_base64?url=${encodeURIComponent(url)}&type=${type}`)
            .then(res => res.json())
            .then(data => {
                if (data.data) {
                    if (el.tagName === 'IMG') {
                        el.src = data.data;
                    } else if (el.tagName === 'VIDEO') {
                        el.innerHTML = `<source src='${data.data}' type='video/mp4'>`;
                        el.load();
                    }
                } else {
                    // fallback
                    if (el.tagName === 'IMG') {
                        el.src = 'https://via.placeholder.com/400x300?text=No+Image';
                    } else if (el.tagName === 'VIDEO') {
                        el.poster = 'https://via.placeholder.com/400x300?text=No+Video';
                    }
                }
            })
            .catch(() => {
                if (el.tagName === 'IMG') {
                    el.src = 'https://via.placeholder.com/400x300?text=No+Image';
                } else if (el.tagName === 'VIDEO') {
                    el.poster = 'https://via.placeholder.com/400x300?text=No+Video';
                }
            });
    });
} 