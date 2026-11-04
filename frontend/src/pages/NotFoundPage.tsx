import { Link } from "react-router-dom";
import { Compass } from "lucide-react";
import { EmptyState } from "../components/common/States";
import { buttonVariants } from "../components/ui/button";

export function NotFoundPage() {
  return (
    <div className="mx-auto max-w-xl py-20">
      <EmptyState
        icon={<Compass className="h-5 w-5" aria-hidden="true" />}
        title="页面不存在"
        description="你访问的地址没有对应的控制台页面。"
        action={
          <Link to="/" className={buttonVariants()}>
            返回文章工作台
          </Link>
        }
      />
    </div>
  );
}
