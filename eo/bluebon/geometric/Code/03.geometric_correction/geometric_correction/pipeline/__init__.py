"""
Geometric Correction Pipeline Module

This module contains all the pipeline step functions for geometric correction.
"""

from .preprocessing import (
    validate_inputs,
    unify_crs,
    crop_to_target_extent,
    normalize_resolution,
    prepare_lowres_images
)

from .initial_matching import (
    ai_feature_matching,
    ransac_filtering,
    scale_to_fullres,
    create_gcps,
    initial_correction
)

from .hierarchical_matching import (
    pyramid_matching_quarter,
    multistage_matching
)

from .precision_correction import (
    create_final_gcps,
    generate_rpc,
    final_correction,
    accuracy_validation,
    apply_rpc_model_directly
)

__all__ = [
    # Preprocessing
    'validate_inputs',
    'unify_crs', 
    'crop_to_target_extent',
    'normalize_resolution',
    'prepare_lowres_images',
    
    # Initial Matching
    'ai_feature_matching',
    'ransac_filtering',
    'scale_to_fullres',
    'create_gcps',
    'initial_correction',
    
    # Hierarchical Matching
    'pyramid_matching_quarter',
    'multistage_matching',
    
    # Precision Correction
    'create_final_gcps',
    'generate_rpc',
    'final_correction',
    'accuracy_validation',
    'apply_rpc_model_directly'
]
