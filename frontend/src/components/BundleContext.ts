import { createContext, useContext } from "react";
import type { EagerBundle } from "../services/dataService";

/** The loaded bundle, for shell-level components (page header status chips) that
 *  should not need it threaded through every page. Pages keep receiving it as a prop. */
export const BundleContext = createContext<EagerBundle | null>(null);

export function useBundle(): EagerBundle | null {
  return useContext(BundleContext);
}
