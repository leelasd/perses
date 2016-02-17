"""
Test systems for perses automated design.

Examples
--------

Alanine dipeptide in various environments (vacuum, implicit, explicit):

>>> from perses.tests.testsystems import AlaninDipeptideSAMS
>>> testsystem = AlanineDipeptideTestSystem()
>>> system_generator = testsystem.system_generator['explicit']
>>> sams_sampler = testsystem.sams_sampler['explicit']

TODO
----
* Have all PersesTestSystem subclasses automatically subjected to a battery of tests.
* Add short descriptions to each class through a class property.

"""

__author__ = 'John D. Chodera'

################################################################################
# IMPORTS
################################################################################

from simtk import openmm, unit
from simtk.openmm import app
import os, os.path
import sys, math
import numpy as np
from functools import partial
from pkg_resources import resource_filename
from openeye import oechem
from openmmtools import testsystems
from perses.tests.utils import sanitizeSMILES

################################################################################
# CONSTANTS
################################################################################

from perses.samplers.thermodynamics import kB

################################################################################
# TEST SYSTEMS
################################################################################

class PersesTestSystem(object):
    """
    Create a consistent set of samplers useful for testing.

    Properties
    ----------
    environments : list of str
        Available environments
    topologies : dict of simtk.openmm.app.Topology
        Initial system Topology objects; topologies[environment] is the topology for `environment`
    positions : dict of simtk.unit.Quantity of [nparticles,3] with units compatible with nanometers
        Initial positions corresponding to initial Topology objects
    system_generators : dict of SystemGenerator objects
        SystemGenerator objects for environments
    proposal_engines : dict of ProposalEngine
        Proposal engines
    themodynamic_states : dict of thermodynamic_states
        Themodynamic states for each environment
    mcmc_samplers : dict of MCMCSampler objects
        MCMCSampler objects for environments
    exen_samplers : dict of ExpandedEnsembleSampler objects
        ExpandedEnsembleSampler objects for environments
    sams_samplers : dict of SAMSSampler objects
        SAMSSampler objects for environments
    designer : MultiTargetDesign sampler
        Example MultiTargetDesign sampler

    """
    def __init__(self):
        self.environments = list()
        self.topologies = dict()
        self.positions = dict()
        self.system_generators = dict()
        self.proposal_engines = dict()
        self.thermodynamic_states = dict()
        self.mcmc_samplers = dict()
        self.exen_samplers = dict()
        self.sams_samplers = dict()
        self.designer = None

class AlanineDipeptideTestSystem(PersesTestSystem):
    """
    Create a consistent set of SAMS samplers useful for testing PointMutationEngine on alanine dipeptide in various solvents.
    This is useful for testing a variety of components.

    Properties
    ----------
    environments : list of str
        Available environments: ['vacuum', 'explicit', 'implicit']
    topologies : dict of simtk.openmm.app.Topology
        Initial system Topology objects; topologies[environment] is the topology for `environment`
    positions : dict of simtk.unit.Quantity of [nparticles,3] with units compatible with nanometers
        Initial positions corresponding to initial Topology objects
    system_generators : dict of SystemGenerator objects
        SystemGenerator objects for environments
    proposal_engines : dict of ProposalEngine
        Proposal engines
    themodynamic_states : dict of thermodynamic_states
        Themodynamic states for each environment
    mcmc_samplers : dict of MCMCSampler objects
        MCMCSampler objects for environments
    exen_samplers : dict of ExpandedEnsembleSampler objects
        ExpandedEnsembleSampler objects for environments
    sams_samplers : dict of SAMSSampler objects
        SAMSSampler objects for environments
    designer : MultiTargetDesign sampler
        Example MultiTargetDesign sampler for implicit solvent hydration free energies

    Examples
    --------

    >>> from perses.tests.testsystems import AlanineDipeptideTestSystem
    >>> testsystem = AlanineDipeptideTestSystem()
    # Build a system
    >>> system = testsystem.system_generators['vacuum'].build_system(testsystem.topologies['vacuum'])
    # Retrieve a SAMSSampler
    >>> sams_sampler = testsystem.sams_samplers['implicit']

    """
    def __init__(self):
        super(AlanineDipeptideTestSystem, self).__init__()
        environments = ['explicit', 'implicit', 'vacuum']

        # Create a system generator for our desired forcefields.
        from perses.rjmc.topology_proposal import SystemGenerator
        system_generators = dict()
        system_generators['explicit'] = SystemGenerator(['amber99sbildn.xml', 'tip3p.xml'],
            forcefield_kwargs={ 'nonbondedMethod' : app.CutoffPeriodic, 'nonbondedCutoff' : 9.0 * unit.angstrom, 'implicitSolvent' : None, 'constraints' : None },
            use_antechamber=False)
        system_generators['implicit'] = SystemGenerator(['amber99sbildn.xml', 'amber99_obc.xml'],
            forcefield_kwargs={ 'nonbondedMethod' : app.NoCutoff, 'implicitSolvent' : app.OBC2, 'constraints' : None },
            use_antechamber=False)
        system_generators['vacuum'] = SystemGenerator(['amber99sbildn.xml'],
            forcefield_kwargs={ 'nonbondedMethod' : app.NoCutoff, 'implicitSolvent' : None, 'constraints' : None },
            use_antechamber=False)

        # Create peptide in solvent.
        from openmmtools.testsystems import AlanineDipeptideExplicit, AlanineDipeptideImplicit, AlanineDipeptideVacuum
        from pkg_resources import resource_filename
        pdb_filename = resource_filename('openmmtools', 'data/alanine-dipeptide-gbsa/alanine-dipeptide.pdb')
        from simtk.openmm.app import PDBFile
        topologies = dict()
        positions = dict()
        pdbfile = PDBFile(pdb_filename)
        topologies['vacuum'] = pdbfile.getTopology()
        positions['vacuum'] = pdbfile.getPositions(asNumpy=True)
        topologies['implicit'] = pdbfile.getTopology()
        positions['implicit'] = pdbfile.getPositions(asNumpy=True)

        # Create molecule in explicit solvent.
        modeller = app.Modeller(topologies['vacuum'], positions['vacuum'])
        modeller.addSolvent(system_generators['explicit'].getForceField(), model='tip3p', padding=9.0*unit.angstrom)
        topologies['explicit'] = modeller.getTopology()
        positions['explicit'] = modeller.getPositions()

        # Set up the proposal engines.
        from perses.rjmc.topology_proposal import PointMutationEngine
        proposal_metadata = { 'ffxmls' : ['amber99sbildn.xml'] }
        proposal_engines = dict()
        allowed_mutations = [[('2','ALA')],[('2','VAL')],[('2','LEU')],[('2','PHE')]]
        for environment in environments:
            proposal_engines[environment] = PointMutationEngine(system_generators[environment], max_point_mutants=1, chain_id='1', proposal_metadata=proposal_metadata, allowed_mutations=allowed_mutations)

        # Generate systems
        systems = dict()
        for environment in environments:
            systems[environment] = system_generators[environment].build_system(topologies[environment])

        # Define thermodynamic state of interest.
        from perses.samplers.thermodynamics import ThermodynamicState
        thermodynamic_states = dict()
        temperature = 300*unit.kelvin
        pressure = 1.0*unit.atmospheres
        thermodynamic_states['explicit'] = ThermodynamicState(system=systems['explicit'], temperature=temperature, pressure=pressure)
        thermodynamic_states['implicit'] = ThermodynamicState(system=systems['implicit'], temperature=temperature)
        thermodynamic_states['vacuum']   = ThermodynamicState(system=systems['vacuum'], temperature=temperature)

        # Create SAMS samplers
        from perses.samplers.samplers import SamplerState, MCMCSampler, ExpandedEnsembleSampler, SAMSSampler
        mcmc_samplers = dict()
        exen_samplers = dict()
        sams_samplers = dict()
        for environment in environments:
            chemical_state_key = proposal_engines[environment].compute_state_key(topologies[environment])
            if environment == 'explicit':
                sampler_state = SamplerState(system=systems[environment], positions=positions[environment], box_vectors=systems[environment].getDefaultPeriodicBoxVectors())
            else:
                sampler_state = SamplerState(system=systems[environment], positions=positions[environment])
            mcmc_samplers[environment] = MCMCSampler(thermodynamic_states[environment], sampler_state)
            mcmc_samplers[environment].nsteps = 5 # reduce number of steps for testing
            mcmc_samplers[environment].verbose = True
            exen_samplers[environment] = ExpandedEnsembleSampler(mcmc_samplers[environment], topologies[environment], chemical_state_key, proposal_engines[environment], options={'nsteps':5})
            exen_samplers[environment].verbose = True
            sams_samplers[environment] = SAMSSampler(exen_samplers[environment])
            sams_samplers[environment].verbose = True

        # Create test MultiTargetDesign sampler.
        from perses.samplers.samplers import MultiTargetDesign
        target_samplers = { sams_samplers['implicit'] : 1.0, sams_samplers['vacuum'] : -1.0 }
        designer = MultiTargetDesign(target_samplers)
        designer.verbose = True

        # Store things.
        self.environments = environments
        self.topologies = topologies
        self.positions = positions
        self.system_generators = system_generators
        self.proposal_engines = proposal_engines
        self.thermodynamic_states = thermodynamic_states
        self.mcmc_samplers = mcmc_samplers
        self.exen_samplers = exen_samplers
        self.sams_samplers = sams_samplers
        self.designer = designer

def load_via_pdbfixer(filename=None, pdbid=None):
    from pdbfixer import PDBFixer
    fixer = PDBFixer(filename=filename, pdbid=pdbid)
    fixer.findMissingResidues()
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(7.0)
    return [fixer.topology, fixer.positions]

class MybTestSystem(PersesTestSystem):
    """
    Create a consistent set of SAMS samplers useful for testing PointMutationEngine on Myb:peptide interaction in various solvents.

    Properties
    ----------
    environments : list of str
        Available environments: ['vacuum', 'explicit', 'implicit']
    topologies : dict of simtk.openmm.app.Topology
        Initial system Topology objects; topologies[environment] is the topology for `environment`
    positions : dict of simtk.unit.Quantity of [nparticles,3] with units compatible with nanometers
        Initial positions corresponding to initial Topology objects
    system_generators : dict of SystemGenerator objects
        SystemGenerator objects for environments
    proposal_engines : dict of ProposalEngine
        Proposal engines
    themodynamic_states : dict of thermodynamic_states
        Themodynamic states for each environment
    mcmc_samplers : dict of MCMCSampler objects
        MCMCSampler objects for environments
    exen_samplers : dict of ExpandedEnsembleSampler objects
        ExpandedEnsembleSampler objects for environments
    sams_samplers : dict of SAMSSampler objects
        SAMSSampler objects for environments
    designer : MultiTargetDesign sampler
        Example MultiTargetDesign sampler for implicit solvent hydration free energies

    Examples
    --------

    >>> from perses.tests.testsystems import MybTestSystem
    >>> testsystem = MybTestSystem()
    # Build a system
    >>> system = testsystem.system_generators['vacuum'].build_system(testsystem.topologies['vacuum'])
    # Retrieve a SAMSSampler
    >>> sams_sampler = testsystem.sams_samplers['implicit']

    """
    def __init__(self):
        super(MybTestSystem, self).__init__()
        environments = ['explicit-complex', 'explicit-peptide', 'implicit-complex', 'implicit-peptide', 'vacuum-complex', 'vacuum-peptide']

        # Create a system generator for our desired forcefields.
        from perses.rjmc.topology_proposal import SystemGenerator
        system_generators = dict()
        system_generators['explicit'] = SystemGenerator(['amber99sbildn.xml', 'tip3p.xml'],
            forcefield_kwargs={ 'nonbondedMethod' : app.CutoffPeriodic, 'nonbondedCutoff' : 9.0 * unit.angstrom, 'implicitSolvent' : None, 'constraints' : None },
            use_antechamber=False)
        system_generators['explicit-complex'] = system_generators['explicit']
        system_generators['explicit-peptide'] = system_generators['explicit']
        system_generators['implicit'] = SystemGenerator(['amber99sbildn.xml', 'amber99_obc.xml'],
            forcefield_kwargs={ 'nonbondedMethod' : app.NoCutoff, 'implicitSolvent' : app.OBC2, 'constraints' : None },
            use_antechamber=False)
        system_generators['implicit-complex'] = system_generators['implicit']
        system_generators['implicit-peptide'] = system_generators['implicit']
        system_generators['vacuum'] = SystemGenerator(['amber99sbildn.xml'],
            forcefield_kwargs={ 'nonbondedMethod' : app.NoCutoff, 'implicitSolvent' : None, 'constraints' : None },
            use_antechamber=False)
        system_generators['vacuum-complex'] = system_generators['vacuum']
        system_generators['vacuum-peptide'] = system_generators['vacuum']

        # Create peptide in solvent.
        from pkg_resources import resource_filename
        pdb_filename = resource_filename('perses', 'data/1sb0.pdb')
        import pdbfixer
        from simtk.openmm.app import PDBFile, Modeller
        topologies = dict()
        positions = dict()
        #pdbfile = PDBFile(pdb_filename)
        [fixer_topology, fixer_positions] = load_via_pdbfixer(pdb_filename)
        topologies['complex'] = fixer_topology
        positions['complex'] = fixer_positions
        modeller = Modeller(topologies['complex'], positions['complex'])
        chains_to_delete = [ chain for chain in modeller.getTopology().chains() if chain.id == 'A' ] # remove chain A
        modeller.delete(chains_to_delete)
        topologies['peptide'] = modeller.getTopology()
        positions['peptide'] = modeller.getPositions()

        # Create all environments.
        for environment in ['implicit', 'vacuum']:
            for component in ['peptide', 'complex']:
                topologies[environment + '-' + component] = topologies[component]
                positions[environment + '-' + component] = positions[component]

        # Set up in explicit solvent.
        for component in ['peptide', 'complex']:
            modeller = app.Modeller(topologies[component], positions[component])
            modeller.addSolvent(system_generators['explicit'].getForceField(), model='tip3p', padding=9.0*unit.angstrom)
            topologies['explicit' + '-' + component] = modeller.getTopology()
            positions['explicit' + '-' + component] = modeller.getPositions()

        # Set up the proposal engines.
        allowed_mutations = list()
        for residue in topologies['peptide'].residues():
            for resname in ['ALA', 'LEU', 'VAL']:
                allowed_mutations.append([(residue.id, resname)])
        from perses.rjmc.topology_proposal import PointMutationEngine
        proposal_metadata = { 'ffxmls' : ['amber99sbildn.xml'] }
        proposal_engines = dict()
        for environment in environments:
            proposal_engines[environment] = PointMutationEngine(system_generators[environment], max_point_mutants=1, chain_id='B', proposal_metadata=proposal_metadata, allowed_mutations=allowed_mutations)

        # Generate systems
        systems = dict()
        for environment in environments:
            systems[environment] = system_generators[environment].build_system(topologies[environment])

        # Define thermodynamic state of interest.
        from perses.samplers.thermodynamics import ThermodynamicState
        thermodynamic_states = dict()
        temperature = 300*unit.kelvin
        pressure = 1.0*unit.atmospheres
        for component in ['peptide', 'complex']:
            thermodynamic_states['explicit' + '-' + component] = ThermodynamicState(system=systems['explicit' + '-' + component], temperature=temperature, pressure=pressure)
            thermodynamic_states['implicit' + '-' + component] = ThermodynamicState(system=systems['implicit' + '-' + component], temperature=temperature)
            thermodynamic_states['vacuum' + '-' + component]   = ThermodynamicState(system=systems['vacuum' + '-' + component], temperature=temperature)

        # Create SAMS samplers
        from perses.samplers.samplers import SamplerState, MCMCSampler, ExpandedEnsembleSampler, SAMSSampler
        mcmc_samplers = dict()
        exen_samplers = dict()
        sams_samplers = dict()
        for environment in environments:
            chemical_state_key = proposal_engines[environment].compute_state_key(topologies[environment])
            if environment[0:8] == 'explicit':
                sampler_state = SamplerState(system=systems[environment], positions=positions[environment], box_vectors=systems[environment].getDefaultPeriodicBoxVectors())
            else:
                sampler_state = SamplerState(system=systems[environment], positions=positions[environment])
            mcmc_samplers[environment] = MCMCSampler(thermodynamic_states[environment], sampler_state)
            mcmc_samplers[environment].nsteps = 5 # reduce number of steps for testing
            mcmc_samplers[environment].verbose = True
            exen_samplers[environment] = ExpandedEnsembleSampler(mcmc_samplers[environment], topologies[environment], chemical_state_key, proposal_engines[environment], options={'nsteps':5})
            exen_samplers[environment].verbose = True
            sams_samplers[environment] = SAMSSampler(exen_samplers[environment])
            sams_samplers[environment].verbose = True

        # Create test MultiTargetDesign sampler.
        from perses.samplers.samplers import MultiTargetDesign
        target_samplers = { sams_samplers['vacuum-complex'] : 1.0, sams_samplers['vacuum-peptide'] : -1.0 }
        designer = MultiTargetDesign(target_samplers)
        designer.verbose = True

        # Store things.
        self.environments = environments
        self.topologies = topologies
        self.positions = positions
        self.system_generators = system_generators
        self.proposal_engines = proposal_engines
        self.thermodynamic_states = thermodynamic_states
        self.mcmc_samplers = mcmc_samplers
        self.exen_samplers = exen_samplers
        self.sams_samplers = sams_samplers
        self.designer = designer

def minimize(testsystem):
    """
    Minimize all structures in test system.

    Parameters
    ----------
    testystem : PersesTestSystem
        The testsystem to minimize.

    """
    for environment in testsystem.environments:
        print("Minimizing '%s'..." % environment)
        integrator = openmm.VerletIntegrator(1.0 * unit.femtoseconds)
        context = openmm.Context(systems[environment], integrator)
        context.setPositions(positions[environment])
        print ("Initial energy is %12.3f kcal/mol" % (context.getState(getEnergy=True).getPotentialEnergy() / unit.kilocalories_per_mole))
        TOL = 1.0
        MAX_STEPS = 50
        openmm.LocalEnergyMinimizer.minimize(context, TOL, MAX_STEPS)
        print ("Final energy is   %12.3f kcal/mol" % (context.getState(getEnergy=True).getPotentialEnergy() / unit.kilocalories_per_mole))
        positions[environment] = context.getState(getPositions=True).getPositions(asNumpy=True)
        del context, integrator

class SmallMoleculeLibraryTestSystem(PersesTestSystem):
    """
    Create a consistent set of samplers useful for testing SmallMoleculeProposalEngine on alkanes in various solvents.
    This is useful for testing a variety of components.

    Properties
    ----------
    environments : list of str
        Available environments: ['vacuum', 'explicit']
    topologies : dict of simtk.openmm.app.Topology
        Initial system Topology objects; topologies[environment] is the topology for `environment`
    positions : dict of simtk.unit.Quantity of [nparticles,3] with units compatible with nanometers
        Initial positions corresponding to initial Topology objects
    system_generators : dict of SystemGenerator objects
        SystemGenerator objects for environments
    proposal_engines : dict of ProposalEngine
        Proposal engines
    themodynamic_states : dict of thermodynamic_states
        Themodynamic states for each environment
    mcmc_samplers : dict of MCMCSampler objects
        MCMCSampler objects for environments
    exen_samplers : dict of ExpandedEnsembleSampler objects
        ExpandedEnsembleSampler objects for environments
    sams_samplers : dict of SAMSSampler objects
        SAMSSampler objects for environments
    designer : MultiTargetDesign sampler
        Example MultiTargetDesign sampler for explicit solvent hydration free energies
    molecules : list
        Molecules in library. Currently only SMILES format is supported.

    Examples
    --------

    >>> from perses.tests.testsystems import AlkanesTestSystem
    >>> testsystem = AlkanesTestSystem()
    # Build a system
    >>> system = testsystem.system_generators['vacuum'].build_system(testsystem.topologies['vacuum'])
    # Retrieve a SAMSSampler
    >>> sams_sampler = testsystem.sams_samplers['explicit']

    """
    def __init__(self):
        super(SmallMoleculeLibraryTestSystem, self).__init__()
        # Expand molecules without explicit stereochemistry and make canonical isomeric SMILES.
        molecules = sanitizeSMILES(self.molecules)
        environments = ['explicit', 'vacuum']

        # Create a system generator for our desired forcefields.
        from perses.rjmc.topology_proposal import SystemGenerator
        system_generators = dict()
        from pkg_resources import resource_filename
        gaff_xml_filename = resource_filename('perses', 'data/gaff.xml')
        system_generators['explicit'] = SystemGenerator([gaff_xml_filename, 'tip3p.xml'],
            forcefield_kwargs={ 'nonbondedMethod' : app.CutoffPeriodic, 'nonbondedCutoff' : 9.0 * unit.angstrom, 'implicitSolvent' : None, 'constraints' : None })
        system_generators['vacuum'] = SystemGenerator([gaff_xml_filename],
            forcefield_kwargs={ 'nonbondedMethod' : app.NoCutoff, 'implicitSolvent' : None, 'constraints' : None })

        #
        # Create topologies and positions
        #
        topologies = dict()
        positions = dict()

        from openmoltools import forcefield_generators
        forcefield = app.ForceField(gaff_xml_filename, 'tip3p.xml')
        forcefield.registerTemplateGenerator(forcefield_generators.gaffTemplateGenerator)

        # Create molecule in vacuum.
        from perses.tests.utils import createOEMolFromSMILES, extractPositionsFromOEMOL
        smiles = molecules[0] # current sampler state
        molecule = createOEMolFromSMILES(smiles)
        topologies['vacuum'] = forcefield_generators.generateTopologyFromOEMol(molecule)
        positions['vacuum'] = extractPositionsFromOEMOL(molecule)

        # Create molecule in solvent.
        modeller = app.Modeller(topologies['vacuum'], positions['vacuum'])
        modeller.addSolvent(forcefield, model='tip3p', padding=9.0*unit.angstrom)
        topologies['explicit'] = modeller.getTopology()
        positions['explicit'] = modeller.getPositions()

        # Set up the proposal engines.
        from perses.rjmc.topology_proposal import SmallMoleculeSetProposalEngine
        proposal_metadata = { }
        proposal_engines = dict()
        for environment in environments:
            proposal_engines[environment] = SmallMoleculeSetProposalEngine(molecules, system_generators[environment])

        # Generate systems
        systems = dict()
        for environment in environments:
            systems[environment] = system_generators[environment].build_system(topologies[environment])

        # Define thermodynamic state of interest.
        from perses.samplers.thermodynamics import ThermodynamicState
        thermodynamic_states = dict()
        temperature = 300*unit.kelvin
        pressure = 1.0*unit.atmospheres
        thermodynamic_states['explicit'] = ThermodynamicState(system=systems['explicit'], temperature=temperature, pressure=pressure)
        thermodynamic_states['vacuum']   = ThermodynamicState(system=systems['vacuum'], temperature=temperature)

        # Create SAMS samplers
        from perses.samplers.samplers import SamplerState, MCMCSampler, ExpandedEnsembleSampler, SAMSSampler
        mcmc_samplers = dict()
        exen_samplers = dict()
        sams_samplers = dict()
        for environment in environments:
            chemical_state_key = proposal_engines[environment].compute_state_key(topologies[environment])
            if environment == 'explicit':
                sampler_state = SamplerState(system=systems[environment], positions=positions[environment], box_vectors=systems[environment].getDefaultPeriodicBoxVectors())
            else:
                sampler_state = SamplerState(system=systems[environment], positions=positions[environment])
            mcmc_samplers[environment] = MCMCSampler(thermodynamic_states[environment], sampler_state)
            mcmc_samplers[environment].nsteps = 5 # reduce number of steps for testing
            mcmc_samplers[environment].verbose = True
            exen_samplers[environment] = ExpandedEnsembleSampler(mcmc_samplers[environment], topologies[environment], chemical_state_key, proposal_engines[environment], options={'nsteps':5})
            exen_samplers[environment].verbose = True
            sams_samplers[environment] = SAMSSampler(exen_samplers[environment])
            sams_samplers[environment].verbose = True

        # Create test MultiTargetDesign sampler.
        from perses.samplers.samplers import MultiTargetDesign
        target_samplers = { sams_samplers['explicit'] : 1.0, sams_samplers['vacuum'] : -1.0 }
        designer = MultiTargetDesign(target_samplers)

        # Store things.
        self.molecules = molecules
        self.environments = environments
        self.topologies = topologies
        self.positions = positions
        self.system_generators = system_generators
        self.proposal_engines = proposal_engines
        self.thermodynamic_states = thermodynamic_states
        self.mcmc_samplers = mcmc_samplers
        self.exen_samplers = exen_samplers
        self.sams_samplers = sams_samplers
        self.designer = designer

class AlkanesTestSystem(SmallMoleculeLibraryTestSystem):
    """
    Library of small alkanes in various solvent environments.
    """
    def __init__(self):
        self.molecules = ['CC', 'CCC', 'CCCC', 'CCCCC', 'CCCCCC']
        super(AlkanesTestSystem, self).__init__()

class KinaseInhibitorsTestSystem(SmallMoleculeLibraryTestSystem):
    """
    Library of clinical kinase inhibitors in various solvent environments.
    """
    def __init__(self):
        # Read SMILES from CSV file of clinical kinase inhibitors.
        from pkg_resources import resource_filename
        smiles_filename = resource_filename('perses', 'data/clinical-kinase-inhibitors.csv')
        import csv
        molecules = list()
        with open(smiles_filename, 'r') as csvfile:
            csvreader = csv.reader(csvfile, delimiter=',', quotechar='"')
            for row in csvreader:
                name = row[0]
                smiles = row[1]
                molecules.append(smiles)
        self.molecules = molecules
        # Intialize
        super(KinaseInhibitorsTestSystem, self).__init__()

class T4LysozymeInhibitorsTestSystem(SmallMoleculeLibraryTestSystem):
    """
    Library of T4 lysozyme L99A inhibitors in various solvent environments.
    """
    def read_smiles(self, filename):
        import csv
        molecules = list()
        with open(filename, 'r') as csvfile:
            csvreader = csv.reader(csvfile, delimiter='\t', quotechar='"')
            for row in csvreader:
                name = row[0]
                smiles = row[1]
                reference = row[2]
                molecules.append(smiles)
        return molecules

    def __init__(self):
        # Read SMILES from CSV file of clinical kinase inhibitors.
        from pkg_resources import resource_filename
        molecules = list()
        molecules += self.read_smiles(resource_filename('perses', 'data/L99A-binders.txt'))
        molecules += self.read_smiles(resource_filename('perses', 'data/L99A-non-binders.txt'))
        self.molecules = molecules
        # Intialize
        super(T4LysozymeInhibitorsTestSystem, self).__init__()

def check_topologies(testsystem):
    """
    Check that all SystemGenerators can build systems for their corresponding Topology objects.
    """
    for environment in testsystem.environments:
        topology = testsystem.topologies[environment]
        try:
            testsystem.system_generators[environment].build_system(topology)
        except Exception as e:
            msg = str(e)
            msg += '\n'
            msg += "topology for environment '%s' cannot be built into a system" % environment
            from perses.tests.utils import show_topology
            show_topology(topology)
            raise Exception(msg)

def checktestsystem(testsystem_class):
    # Instantiate test system.
    testsystem = testsystem_class()
    # Check topologies
    check_topologies(testsystem)

def test_testsystems():
    """
    Test instantiation of all test systems.
    """
    testsystem_names = ['T4LysozymeInhibitorsTestSystem', 'KinaseInhibitorsTestSystem', 'AlkanesTestSystem', 'AlanineDipeptideTestSystem']
    niterations = 5 # number of iterations to run
    for testsystem_name in testsystem_names:
        import perses.tests.testsystems
        testsystem_class = getattr(perses.tests.testsystems, testsystem_name)
        f = partial(checktestsystem, testsystem_class)
        f.description = "Testing %s" % (testsystem_name)
        yield f

if __name__ == '__main__':
    # Test Myb system
    testsystem = MybTestSystem()
    testsystem.exen_samplers['vacuum-peptide'].pdbfile = open('myb-vacuum.pdb', 'w')
    testsystem.exen_samplers['vacuum-complex'].pdbfile = open('myb-complex.pdb', 'w')
    testsystem.exen_samplers['vacuum-complex'].options={'nsteps':2500}
    testsystem.exen_samplers['vacuum-peptide'].options={'nsteps':2500}
    testsystem.mcmc_samplers['vacuum-complex'].nsteps = 2500
    testsystem.mcmc_samplers['vacuum-peptide'].nsteps = 2500
    #testsystem.designer.verbose = True
    #testsystem.designer.run(niterations=100)
    testsystem.exen_samplers['vacuum-peptide'].verbose=True
    testsystem.exen_samplers['vacuum-peptide'].run(niterations=100)
