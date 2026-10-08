function hitTestContains(x, y) {
  const topmost = document.elementFromPoint(x, y);
  return topmost === this || this.contains(topmost);
}
