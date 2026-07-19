import { DataExplorer } from "./DataExplorer";
import data from "./data/results.json";
import targetCoverage from "./data/target_coverage.json";

export default function Home() {
  return <DataExplorer data={data} targetCoverage={targetCoverage} />;
}
