import { setActiveKotoComposerText } from '../shared/active-composer';

const SUGGESTION_SELECTOR = '[data-koto-suggestion]';

function bindPrimaryComposerSuggestions(): void {
  document.addEventListener('click', (event) => {
    const target = (event.target as Element | null)?.closest(SUGGESTION_SELECTOR) as HTMLElement | null;
    if (!target) return;
    const text = String(target.dataset.kotoSuggestion || '').trim();
    if (!text) return;
    event.preventDefault();
    setActiveKotoComposerText(text);
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
}

bindPrimaryComposerSuggestions();
