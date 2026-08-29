/* A minimum deck-stage, for the tests only.

   deck-comments.js is written against a deck runtime it does not ship: slides
   are `deck-stage > section`, the live one carries `data-deck-active`, the
   label is `data-screen-label`, and `stage.goTo(i)` navigates. This is the
   smallest thing that satisfies that contract, so the tests drive the real
   asset rather than a mock of it. */
class DeckStage extends HTMLElement {
  get sections() {
    // Re-read every time: a reorder moves the sections in the light DOM.
    return Array.prototype.slice.call(this.querySelectorAll(':scope > section'));
  }
  connectedCallback() {
    this.index = 0;
    // Marks the live stage. deck.css hangs the show/hide rule off this,
    // so an overview thumbnail is not hidden by it.
    this.setAttribute('data-live', '');
    this.goTo(0);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') this.goTo(this.index + 1);
      if (e.key === 'ArrowLeft' || e.key === 'PageUp') this.goTo(this.index - 1);
    });
  }
  goTo(i) {
    const all = this.sections;
    if (i < 0 || i >= all.length) return;
    this.index = i;
    all.forEach((s, k) => {
      if (k === i) s.setAttribute('data-deck-active', '');
      else s.removeAttribute('data-deck-active');
    });
  }
}
customElements.define('deck-stage', DeckStage);
