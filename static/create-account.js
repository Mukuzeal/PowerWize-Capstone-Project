function togglePw(id, btn) {
  var input = document.getElementById(id);
  var shown = input.type === 'text';
  input.type = shown ? 'password' : 'text';
  btn.innerHTML = shown
    ? '<i class="fa-solid fa-eye"></i>'
    : '<i class="fa-solid fa-eye-slash"></i>';
}
