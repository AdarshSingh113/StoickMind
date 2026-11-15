import { Compass, Hammer } from "lucide-react";
import { Link, useLocation } from "react-router";
import { EmptyState } from "@/components/empty";
import { Button } from "@/components/ui/button";

const SOON: Record<string, [string, string]> = {
  "/customers": ["Customers", "R3"], "/ask": ["Ask your data", "R4"], "/performance": ["AI performance", "R4"],
  "/campaigns": ["Campaigns", "R5"], "/helpdesk": ["Helpdesk", "R5"], "/studio": ["Agent Studio", "R6"],
};

export function ComingSoon() {
  const [title, milestone] = SOON[useLocation().pathname] ?? ["This page", "a later milestone"];
  return (
    <div className="grid h-full place-items-center">
      <EmptyState icon={Hammer} title={`${title} is coming in ${milestone}`}
        body="It already works in the classic Streamlit dashboard (streamlit run app.py) while the new app is being built screen by screen."
        action={<Link to="/"><Button>Back to overview</Button></Link>} />
    </div>
  );
}

export function NotFound() {
  return (
    <div className="grid h-full place-items-center">
      <EmptyState icon={Compass} title="Page not found" body="That link doesn't lead anywhere." action={<Link to="/"><Button>Go to overview</Button></Link>} />
    </div>
  );
}
