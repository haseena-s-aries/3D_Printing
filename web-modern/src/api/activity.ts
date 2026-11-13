/** App-wide "something is happening" counter for the top progress bar: saves (POST/PATCH/PUT/DELETE), file opens and
 *  the first load of a page's data. Background polling (reloads of data already shown) is not counted. */
type Listener = (busy: boolean) => void;
let count = 0;
const listeners = new Set<Listener>();

function emit() {
  for (const l of listeners) l(count > 0);
}

export async function track<T>(work: Promise<T>): Promise<T> {
  count += 1;
  emit();
  try {
    return await work;
  } finally {
    count = Math.max(0, count - 1);
    emit();
  }
}

export function onActivity(l: Listener): () => void {
  listeners.add(l);
  return () => { listeners.delete(l); };
}
