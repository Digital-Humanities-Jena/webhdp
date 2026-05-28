import { useRouteError, isRouteErrorResponse, Link } from "react-router-dom";
import { AlertCircle } from "lucide-react";

export default function ErrorPage() {
    const error = useRouteError();
    let errorMessage: string;

    if (isRouteErrorResponse(error)) {
        errorMessage = error.statusText || error.data?.message || "Unknown Error";
    } else if (error instanceof Error) {
        errorMessage = error.message;
    } else if (typeof error === 'string') {
        errorMessage = error;
    } else {
        errorMessage = 'Unknown error occurred';
    }

    return (
        <div className="flex h-screen w-full flex-col items-center justify-center bg-background p-4 text-center">
            <div className="rounded-full bg-destructive/10 p-4 mb-4">
                <AlertCircle className="h-10 w-10 text-destructive" />
            </div>
            <h1 className="text-4xl font-bold tracking-tight mb-2">Oops!</h1>
            <p className="text-muted-foreground mb-6">Sorry, an unexpected error has occurred.</p>
            <div className="rounded-md bg-secondary p-4 mb-6 max-w-md w-full overflow-auto">
                <code className="text-sm font-mono text-destructive dark:text-red-400">
                    {errorMessage}
                </code>
            </div>
            <Link
                to="/"
                className="inline-flex items-center justify-center rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 bg-primary text-primary-foreground hover:bg-primary/90 h-10 px-4 py-2"
            >
                Return to Dashboard
            </Link>
        </div>
    );
}
