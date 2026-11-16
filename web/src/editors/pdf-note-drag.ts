import { viewportDeltaToElement } from '../shared/ui-scale';

export function dragPdfNote(event: MouseEvent, popup: HTMLElement): void {
  const startX = event.clientX;
  const startY = event.clientY;
  const startLeft = parseFloat(popup.style.left);
  const startTop = parseFloat(popup.style.top);
  const onMove = (moveEvent: MouseEvent) => {
    const coordinateHost = popup.parentElement || popup;
    const delta = viewportDeltaToElement(
      coordinateHost,
      moveEvent.clientX - startX,
      moveEvent.clientY - startY,
    );
    popup.style.left = `${startLeft + delta.x}px`;
    popup.style.top = `${startTop + delta.y}px`;
  };
  const onUp = () => {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}
