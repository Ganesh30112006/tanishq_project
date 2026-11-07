// Applied before first paint so dark-mode users never see a white flash.
// A file rather than an inline script, so the Content-Security-Policy can
// forbid inline script entirely.
(function () {
  var mq = window.matchMedia('(prefers-color-scheme: dark)');
  var apply = function () { document.documentElement.classList.toggle('dark', mq.matches); };
  apply();
  mq.addEventListener('change', apply);
})();
