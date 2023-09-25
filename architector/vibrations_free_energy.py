import ase
from ase.vibrations import Vibrations
from ase.thermochemistry import IdealGasThermo
import numpy as np
from architector import arch_context_manage


def vibration_analysis(atoms,hess,mode_type='mass_weighted_unnormalized'):
    """vibration analysis
    Gives modes, energies,frequencies, reduced masses, AND force constants
    from hessian for the requested atoms system
    
    Influenced by torchani code: 
    https://github.com/aiqm/torchani/blob/master/torchani/utils.py
    And ASE vibrations data class:
    https://gitlab.com/ase/ase/-/blob/master/ase/vibrations/data.py

    Largely same implementation as described in Gaussian:
    https://gaussian.com/vib/

    Parameters 
    ----------
    atoms : ase.atoms.Atoms
        Ase atoms with N atoms corresponding to hessian.
    hess : np.ndarray
        Hessian in eV/Angstroms^2 either generated by ase.vibrations.Vibrations or from an external program.
    mode_type : str, optional
        What type of scaling to use for the modes, default 'mass_weighted_unnormalized'
        direct_eigen_vectors = eigenvectors of M^(-1/2)*Hess*M^(-1/2)
        mass_weighted_unnormalized = same ase ASE 
        mass_weighted_normalized = normalized (same as Guassian) - see 
        https://gaussian.com/vib/ 
    
    Returns
    -------
    energies : np.ndarray
        Energies of the modes in eV 
    modes : np.ndarray 
        Normal modes of the type requested (units vary).
    fconstants : np.ndarray
        Force constants for the modes in eV/Angstroms^2
    rmasses : np.ndarray
        Reduced masses of the modes in MW
    frequencies : np.ndarray
        Frequencies in cm^-1 of the modes.
    """
    n_atoms = len(atoms)
    masses = atoms.get_masses()
    
    if not np.all(masses):
        raise ValueError('Zero mass encountered in one or more of '
                         'the vibrated atoms. Use Atoms.set_masses()'
                         ' to set all masses to non-zero values.')
    # Hessian in eV/(Angstroms)^2
    mass_weights = np.repeat(masses**-0.5, 3)  # Units 1/sqrt(MW)
    mweight_H = mass_weights * hess * mass_weights[:, np.newaxis] # Units eV/(Angstroms^2)/MW
    
    eig_values, eig_vectors = np.linalg.eigh(mweight_H)
    
    unit_conversion = ase.units._hbar * ase.units.m / np.sqrt(ase.units._e * ase.units._amu) 
    
    energies = unit_conversion * eig_values.astype(complex)**0.5 # Unit sqrt(eV/Angstroms^2/MW) gives 1/s, convert to eV via frequency

    frequencies = energies / ase.units.invcm # Convert to frequency from energy.

    # Modes in columns
    mw_normalized = eig_vectors.T # Unitless
    md_unnormalized = mw_normalized * mass_weights # Units are 1/sqrt(MW)
    norm_factors = 1 / np.linalg.norm(md_unnormalized, axis=0)  #units are sqrt(MW)
    md_normalized = md_unnormalized * norm_factors # Unitless

    # Reshape modes.
    mw_normalized = mw_normalized.reshape(n_atoms * 3, n_atoms, 3)
    md_unnormalized = md_unnormalized.reshape(n_atoms * 3, n_atoms, 3)
    md_normalized = md_normalized.reshape(n_atoms * 3, n_atoms, 3)
    
    rmasses = norm_factors**2  # units are MW
    
    fconstants = eig_values.astype(complex) * rmasses  # units are eV/(Angstroms)^2 to define an R
    # kB*T in ase units in units of eV. So plugging into normal mode sampling gives Angstrom.

    modes = None
    if mode_type == 'direct_eigen_vectors': # Unitless
        modes = mw_normalized
    elif mode_type == 'mass_weighted_unnormalized': # Mass weighted has units of 1/sqrt(MW)
        modes =  md_unnormalized
    elif mode_type == 'mass_weighted_normalized': # Unitless
        modes = md_normalized
    else:
        raise ValueError('Mode Type requested unknown.')
    
    return energies, modes, fconstants, rmasses, frequencies
    

def calc_free_energy(relaxed_atoms ,temp=298.15, pressure=101325, geometry='nonlinear'):
    """calc_free_energy utility function to calculate free energy of relaxed structures with
    ASE calculators added.

    Uses the ideal gas rigid rotor harmonic oscillator (IGRRHO) approach

    Parameters
    ----------
    relaxed_atoms : ase.atoms.Atoms
        relaxed structures with calculator attached (usually XTB)
    temp : float, optional
        temperature in kelvin, by default 298.15
    pressure : int, optional
        pressure in pascal, by default 101325 Pa
    geometry : str, optional
        'linear','nonlinear' , by default 'nonlinear'

    Returns
    -------
    G, float
       free energy in eV
    thermo, ase.thermo
        ASE thermo calculator
    """
    with arch_context_manage.make_temp_directory() as _:
        potentialenergy = relaxed_atoms.get_potential_energy()
        vib = Vibrations(relaxed_atoms)
        vib.run()
        vib_energies = vib.get_energies()
        nunpaired = np.sum(relaxed_atoms.get_initial_magnetic_moments())

        thermo = IdealGasThermo(vib_energies=vib_energies,
                                potentialenergy=potentialenergy,
                                atoms=relaxed_atoms,
                                geometry=geometry,
                                symmetrynumber=2, spin=nunpaired/2)
        G = thermo.get_gibbs_energy(temperature=temp, pressure=pressure)
    return G, thermo