import React from 'react';

/** daisyUI loading indicator, replacing MUI's `CircularProgress`. */
const SIZES = { xs: 'loading-xs', sm: 'loading-sm', md: 'loading-md', lg: 'loading-lg' };

const Spinner = ({ size = 'md', className = '' }) => (
  <span className={`loading loading-spinner ${SIZES[size]} ${className}`} role="status" aria-live="polite" />
);

export default Spinner;
