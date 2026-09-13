(function () {
  var print = document.getElementById("btn-print");
  if (print) print.addEventListener("click", function () { window.print(); });
  var links = Array.from(document.querySelectorAll(".guida-toc a"));
  var sections = links.map(function (a) { return document.querySelector(a.getAttribute("href")); });
  function update() {
    var y = window.scrollY + 100, current = 0;
    sections.forEach(function (s, i) { if (s && s.offsetTop <= y) current = i; });
    links.forEach(function (a, i) { a.classList.toggle("active", i === current); });
  }
  window.addEventListener("scroll", update, { passive: true });
  update();
})();
