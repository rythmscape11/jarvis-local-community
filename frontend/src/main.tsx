import ReactDOM from "react-dom/client";
import App from "./App";
import { OwnerBoundary } from "./OwnerSecurity";
import "./style.css";
ReactDOM.createRoot(document.getElementById("root")!).render(<OwnerBoundary><App /></OwnerBoundary>);
