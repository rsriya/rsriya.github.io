document.addEventListener("DOMContentLoaded", function () {
    const footer = document.getElementById("footer");

    if (!footer) return;

    footer.innerHTML = `
        <footer class="site-footer">

            <div class="footer-main">

                <div class="footer-brand">
                    <h2>DMV PROTON THERAPY<br>COLLABORATIVE</h2>
                    <p>
                        Washington, DC • Maryland • Virginia
                    </p>
                </div>

                <div class="footer-column">
                    <h3>EXPLORE</h3>
                    <a href="about.html">About</a>
                    <a href="centers.html">Centers</a>
                    <a href="symposium.html">Symposium</a>
                    <a href="resources.html">Education</a>
                    <a href="news.html">News</a>
                </div>

                <div class="footer-column">
                    <h3>CONTACT</h3>
                    <a href="mailto:DMVprotonsymposium@gmail.com">
                        DMVprotonsymposium@gmail.com
                    </a>
                </div>

            </div>

            <div class="footer-bottom">
                <p>
                    © ${new Date().getFullYear()} DMV Proton Therapy Collaborative
                </p>
            </div>

        </footer>
    `;
});
