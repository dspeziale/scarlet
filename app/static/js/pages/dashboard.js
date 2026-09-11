Scarlet.pages.dashboard = function (root) {
  const trend = JSON.parse(root.dataset.trend || "[]");
  const canvas = document.getElementById("deploy-trend");
  if (!canvas || typeof Chart === "undefined") return;
  new Chart(canvas, {
    type: "bar",
    data: {
      labels: trend.map((t) => t.date.substring(5)),
      datasets: [
        { label: "Success", data: trend.map((t) => t.success), backgroundColor: "#198754", stack: "d" },
        { label: "Failed", data: trend.map((t) => t.failed), backgroundColor: "#dc3545", stack: "d" },
        { label: "Other", data: trend.map((t) => t.other), backgroundColor: "#adb5bd", stack: "d" },
      ],
    },
    options: { responsive: true, plugins: { legend: { position: "bottom" } }, scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } } },
  });
};
