window.addEventListener("load", function () {
  var el = document.getElementById("swagger-ui");
  window.ui = SwaggerUIBundle({ url: el.dataset.specUrl, dom_id: "#swagger-ui", deepLinking: true, requestInterceptor: function (req) { var m = document.cookie.match(/csrf_token=([^;]+)/); return req; } });
});
