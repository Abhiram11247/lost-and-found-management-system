// Small client-side helpers. The server validates everything again, so these
// only make the interface friendlier.

document.addEventListener("DOMContentLoaded", function () {
  // Ask for confirmation before forms marked with data-confirm (e.g. delete).
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm)) {
        event.preventDefault();
      }
    });
  });
});
