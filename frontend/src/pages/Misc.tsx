import { Compass } from "lucide-react";
import { Link } from "react-router";
import { EmptyState } from "@/components/empty";
import { Button } from "@/components/ui/button";

export function NotFound() {
  return (
    <div className="grid h-full place-items-center">
      <EmptyState icon={Compass} title="Page not found" body="That link doesn't lead anywhere." action={<Link to="/app"><Button>Go to overview</Button></Link>} />
    </div>
  );
}
