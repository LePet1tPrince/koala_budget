import React, { useEffect, useRef } from 'react';

/**
 * Mounts a Chart.js chart imperatively on a canvas ref and tears it down on
 * unmount/re-run. `create(canvas)` must return the Chart instance (or null).
 */
const ChartCanvas = ({ create, deps = [], height = 280, testId }) => {
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current) return undefined;
    const chart = create(canvasRef.current);
    return () => chart?.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return (
    <div style={{ height }}>
      <canvas ref={canvasRef} data-testid={testId} />
    </div>
  );
};

export default ChartCanvas;
