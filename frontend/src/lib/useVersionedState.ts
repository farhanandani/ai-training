import { useState } from "react";

/** State that resets to `initial` whenever `version` changes (e.g. dataset_version after a reset / upload / save). */
export function useVersionedState<T>(version: number | undefined, initial: T) {
  const [state, setState] = useState<T>(initial);
  const [seen, setSeen] = useState(version);
  if (seen !== version) {
    // adjust state during render (React docs: storing information from previous renders)
    setSeen(version);
    setState(initial);
  }
  return [state, setState] as const;
}
