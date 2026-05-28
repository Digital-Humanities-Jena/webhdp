import React from 'react';

interface BreadcrumbsProps {
    path: string;
    onNavigate: (path: string) => void;
}

export function Breadcrumbs({ path, onNavigate }: BreadcrumbsProps) {
    // Split path into segments, ignoring empty strings
    const segments = path.split('/').filter(Boolean);

    return (
        <div className="flex items-center space-x-1">
            {segments.map((segment, index) => {
                // Construct path up to this segment
                // e.g. /foo/bar -> /foo for "foo", /foo/bar for "bar"
                const segmentPath = '/' + segments.slice(0, index + 1).join('/');

                return (
                    <React.Fragment key={index}>
                        <button
                            onClick={() => onNavigate(segmentPath)}
                            className="hover:text-primary hover:underline transition-colors px-1"
                        >
                            {segment}
                        </button>
                        {index < segments.length - 1 && (
                            <span className="text-muted-foreground/50">/</span>
                        )}
                    </React.Fragment>
                );
            })}
        </div>
    );
}
