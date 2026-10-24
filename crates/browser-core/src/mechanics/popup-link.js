function popupLink() {
  if (
    !(this instanceof HTMLAnchorElement) ||
    this.target.toLowerCase() !== "_blank" ||
    this.hasAttribute("download")
  ) {
    return null;
  }
  const url = new URL(this.href);
  if (
    (url.protocol !== "http:" && url.protocol !== "https:") ||
    url.username ||
    url.password
  ) {
    return null;
  }
  return url.href;
}
