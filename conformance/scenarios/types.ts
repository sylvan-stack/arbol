import type { ScenarioHome } from '../harness.js';
export interface Scenario {
  id: string;
  title: string;
  scope: string;
  covers: string[];
  run(home: ScenarioHome): Promise<void>;
}
