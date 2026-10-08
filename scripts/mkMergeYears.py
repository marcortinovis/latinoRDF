#!/usr/bin/env python3

import sys
argv = sys.argv
sys.argv = argv[:1]

import argparse

import os
import re

import ROOT



#
# default parser
#

def defaultParser():
    sys.argv = argv

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        "--pycfg",
        dest="pycfg",
        help="input configuration file",
        default="merge_configuration.py",
    )

    return parser


#
# load configurations into the parser, according to configuration.py
#

def loadDefaultOptions(parser, pycfg=None, quiet=False):

    if pycfg != None and os.path.exists(pycfg):
        # print ("loadDefaultOptions: pycfg = ", pycfg)
        handle = open(pycfg,'r')
        local_variables = {}
        exec(handle.read(),local_variables)
        handle.close()
        # clean the dictionary to remove globals due to "exec" funcionality
        local_variables = {k: v for k, v in local_variables.items() if not (k.startswith('__') and k.endswith('__'))}
        for opt_name, opt_value in local_variables.items():
          parser.add_argument('--' + opt_name, default=opt_value)
        return
    else:
        return




# ----------------------------------------------------- Merge Years: e.g. Run 2, Run 3, ... --------------------------------------


class MergerFactory:

    # _____________________________________________________________________________
    def __init__(self):
        self._fileIn = None

    # _____________________________________________________________________________
    def merge(
        self,
        tag,
        variables,
        cuts,
        samples,
        nuisances,
        foldersToMerge,
        foldersToMergeNuisancesFiles,
        inPath
   ):


       #
       # expand cuts, unrolling the categories
       #

       list_cuts = {}
       for cutName, cut in cuts.items():

         if isinstance(cut, dict):
           # "cut" is a dictionary
           expression = cut['expr']
           categories = cut.get('categories', {})
           if categories :
             list_cuts[ cutName ] = "(" + expression + ")"   # add the un-categorized phase space too! it comes "for free"
             for category_name, category in categories.items():
               list_cuts[ cutName + "_" + category_name] = "(" + expression + ") && (" + category + ")"
           else :
             list_cuts[ cutName ] = expression
         else :
           list_cuts[ cutName ] = cut

       self._cuts = list_cuts


       new_list_of_nuisances = nuisances


       #
       # Get all the samples from all the years. This is needed for the definition of the nuisances
       #
       foldersToMergeSamplesFiles = {
           k : os.path.join(p["folder"], 'samples.py') for k, p in foldersToMerge.items()
           }
       # print ("foldersToMergeSamplesFiles   = ", foldersToMergeSamplesFiles)


       #
       # get all the niusances from all the years
       #
       all_nuisances = {}

       for folderHR, year_nuisances in foldersToMergeNuisancesFiles.items() :
         year_samples = foldersToMergeSamplesFiles[folderHR]

         print ("year_nuisances = ", year_nuisances)
         print ("year_samples   = ", year_samples)

         #
         # read list of samples and nuisance in one go --> dependencies are respected in this way
         #

         with open(year_samples, 'r') as f_samples:
           handle_samples = f_samples.read()
         with open(year_nuisances, 'r') as f_nuisances:
           handle_nuisances = f_nuisances.read()

         handle_unique = handle_samples + "\n# --- End of Samples / Start of Nuisances ---\n" + handle_nuisances

         exec_context = {'os': os,
                         'samples': {},
                         'nuisances': {}
                        }
         # exec_context = globals().copy() # FIXME not 100% sure about handling of global variables, e.g. treeBaseDir ... the same in all years? Will this work?
         exec(handle_unique, exec_context)
         nuisances = exec_context.get('nuisances', {})
         nuisances = {k: v for k, v in nuisances.items() if not (k.startswith('__') and k.endswith('__'))}

         all_nuisances[folderHR] = nuisances

         print (" all_nuisances[", folderHR, "] = ", all_nuisances[folderHR])


       #
       # get all the root files with the histograms from the different years
       #
       new_root_file_name = inPath+'Run2/'+"histos_"     + tag + ".root"
       # print (" new_root_file_name = ", new_root_file_name)
       rootFileNew = ROOT.TFile.Open( new_root_file_name, "RECREATE")

       histograms = {}

       for folderHR, folder in foldersToMerge.items():
         # copy the default root file for bookkeeping

         # root_file_joined.root FIXME
         old_root_file_name = inPath + folder["folder"][3:] + "/" + "rootFile" + "/root_file_joined.root" ##### mcortino
         # old_root_file_name = folder["folder"] + "/" + "rootFile" + "/mkShapes__" + folder["tag"] + ".root"
         new_root_file_name = "year_" + folderHR + "_histos_" + folder["tag"] + ".root"
         os.system ("cp " + old_root_file_name + "   " + new_root_file_name )
         print(new_root_file_name) ## mcortino debug
         rootFile    = ROOT.TFile.Open( new_root_file_name, "READ")

         #
         # the following instruction is essential, because in ROOT the TH1F is owned by the root file
         # and in python here for some reason the root file is closed (but why why why ...),
         # thus all histograms deleted (None pointer) during the loop ...
         # By doing "cd" the histograms are owned by the output file, thus surviving
         #
         rootFileNew.cd()
         # get the histograms
         histograms[folderHR] = {}

         # loop over cuts
         for cutName in cuts :
           # loop over variables
           for variableName, variable in variables.items():
             folder_name = cutName + "/" + variableName
             histograms[folderHR][folder_name] = {}
             folder_in_file = rootFile.Get(folder_name)

             for k in folder_in_file.GetListOfKeys():
               h = k.ReadObj()
               # only 1d histograms supported
               histoName = h.GetName()
               match = re.search("histo_", histoName)
               if not match:
                 continue
               histograms[folderHR][folder_name][histoName] = h.Clone()  # clone is needed, otherwise None in the dictionary


       #
       # add the nominals for all the years
       #

       rootFileNew.cd()


       # loop over cuts
       for cutName in cuts :
         # loop over variables
         for variableName, variable in variables.items():
           folder_name = cutName + "/" + variableName
           rootFileNew.cd()
           rootFileNew.mkdir(folder_name)
           rootFileNew.cd(folder_name)

           # loop over samples
           for sampleName, sample in samples.items():

             histos_to_be_summed = []

             for folderHR, folder in foldersToMerge.items():
               histoName = "histo_" + sampleName
               histos_to_be_summed.append(histograms[folderHR][folder_name][histoName])

             summed_histo = histos_to_be_summed[0].Clone()

             for hh in histos_to_be_summed[1:] :  # skip first one
               summed_histo.Add(hh)

             summed_histo.Write()


       #
       # Now let's handle the nuisances
       #

       rootFileNew.cd()

       print (" new_list_of_nuisances = ", new_list_of_nuisances)

       # loop over cuts
       for cutName in cuts :
         # loop over variables
         for variableName, variable in variables.items():
           folder_name = cutName + "/" + variableName
           rootFileNew.cd()
           rootFileNew.cd(folder_name)

           # loop over nuisances
           for nuisanceName, nuisance in new_list_of_nuisances.items():

             #
             # if the combined nuisance type is lnN, don't touch anything, nothing to be done on histograms level
             #
             if nuisance['type'] == 'lnN' :
               continue

             elif 'name' in nuisance.keys() :

               # loop over samples
               for sampleName, sample in samples.items():

                 # nameTempUp   = 'histo_' + str(sampleName) + '_' + (nuisance['name']) + 'Up'
                 # nameTempDown = 'histo_' + str(sampleName) + '_' + (nuisance['name']) + 'Down'
                 nameTempUp   = 'histo_' + str(sampleName) + '_' + (nuisance['name']) + 'up'
                 nameTempDown = 'histo_' + str(sampleName) + '_' + (nuisance['name']) + 'do'
                 nameTemp     = 'histo_' + str(sampleName)

                 histos_up_to_be_summed = []
                 histos_down_to_be_summed = []

                 histos_up_to_be_summed_weights = []
                 histos_down_to_be_summed_weights = []

                 for folderHR, folder in foldersToMerge.items():

                   # print ("folderHR = ", cutName, " :: ", nuisanceName, "::", folderHR)

                   #
                   # If the histogram up and down are present in the input root files, add the histograms up/down
                   # No matter if then the nuisance is not a shape nuisance but lnN ... still, you add the histograms!
                   # eh perbacco, the histogram exists, then you add it, you might change idea later on
                   #
                   if nameTempUp in histograms[folderHR][folder_name].keys() and nameTempDown in histograms[folderHR][folder_name].keys() :
                     histos_up_to_be_summed.append  ( histograms[folderHR][folder_name][nameTempUp] )
                     histos_down_to_be_summed.append( histograms[folderHR][folder_name][nameTempDown] )
                     histos_up_to_be_summed_weights.append ( 1.0 )
                     histos_down_to_be_summed_weights.append ( 1.0 )

                     # print ("     --->>>>>>>>>>>>>>> added = ", nameTempUp)

                   else :
                     #
                     # it might be that for that particular sample
                     # or for a specific year in the combination
                     # the nuisance is not defined or missing.
                     # In this case, ok, nothing to be done: the up/down variation should be taken as the nominal
                     #
                     # The nuisance might have been a lnN ... this has to be handled properly
                     #

                     # print ("     not added?  ", nameTempUp)

                     # print ("     Check:", nuisanceName, " in all_nuisances[",folderHR, "] = ", all_nuisances[folderHR])

                     if nuisanceName in all_nuisances[folderHR].keys() :
                       # print ("     I should add the nuisance, that was -->", all_nuisances[folderHR][nuisanceName]['type'], " and was the sample ", sampleName, "  there? ", sampleName in all_nuisances[folderHR][nuisanceName]['samples'].keys())

                       if all_nuisances[folderHR][nuisanceName]['type'] == 'lnN' and  sampleName in all_nuisances[folderHR][nuisanceName]['samples'].keys() :
                         #
                         #    lnN nuisances:
                         #    the up/down could be given separately:   '1.03/0.99'
                         #    or unique :                              '1.02'
                         #
                         histos_up_to_be_summed.append  ( histograms[folderHR][folder_name][nameTemp] )
                         histos_down_to_be_summed.append( histograms[folderHR][folder_name][nameTemp] )
                         if "/" not in all_nuisances[folderHR][nuisanceName]['samples'][sampleName]:
                           histos_up_to_be_summed_weights.append ( float(all_nuisances[folderHR][nuisanceName]['samples'][sampleName]) )
                           histos_down_to_be_summed_weights.append ( 1. / float(all_nuisances[folderHR][nuisanceName]['samples'][sampleName]) )
                         else :
                           val_up, val_down = all_nuisances[folderHR][nuisanceName]['samples'][sampleName].split("/")
                           histos_up_to_be_summed_weights.append ( val_up )
                           histos_down_to_be_summed_weights.append ( val_down )

                     else:
                       # print ("     nuisanceName[", nuisanceName, "] is not in the list of nuisances to be used in the summed version")
                       histos_up_to_be_summed.append  ( histograms[folderHR][folder_name][nameTemp] )
                       histos_down_to_be_summed.append( histograms[folderHR][folder_name][nameTemp] )
                       histos_up_to_be_summed_weights.append   ( 1.0 )
                       histos_down_to_be_summed_weights.append ( 1.0 )


                 #
                 # if the nuisance has NO effect on a sample, the histograms are not even created, thus it's not possible to merge them
                 #
                 # if len(histos_up_to_be_summed) >= 1:
                 if len(histos_up_to_be_summed) >= 1 and sampleName != "DATA": # FIXME hardcoded 'DATA'
                   print ("nuisanceName to be written:", nuisanceName, "for sample: ", sampleName, " cut: ", cutName, " variable: ", variableName)
                   summed_up_histo = histos_up_to_be_summed[0].Clone()
                   summed_up_histo.Scale(histos_up_to_be_summed_weights[0])
                   ihh = 0
                   for hh in histos_up_to_be_summed[1:] :  # skip first one
                     ihh += 1
                     summed_up_histo.Add(hh, histos_up_to_be_summed_weights[ihh])
                   # set the name properly, mentioning the nuisance
                   summed_up_histo.SetName (nameTempUp)
                   summed_up_histo.Write()

                   summed_down_histo = histos_down_to_be_summed[0].Clone()
                   summed_down_histo.Scale(histos_down_to_be_summed_weights[0])
                   ihh = 0
                   for hh in histos_down_to_be_summed[1:] :  # skip first one
                     ihh += 1
                     summed_down_histo.Add(hh, histos_down_to_be_summed_weights[ihh])
                   summed_down_histo.SetName (nameTempDown)
                   summed_down_histo.Write()


       return True




if __name__ == '__main__':
    sys.argv = argv

    ROOT.gROOT.SetBatch(True)

    header = """
         ------------------------------------------------------------------------------
         '          __  __                      __   __                               '
         '         |  \\/  | ___ _ __ __ _  ___  \\ \\ / /__  __ _ _ __ ___              '
         '         | |\\/| |/ _ \\ '__/ _` |/ _ \\  \\ V / _ \\/ _` | '__/ __|             '
         '         | |  | |  __/ | | (_| |  __/   | |  __/ (_| | |  \\__ \\             '
         '         |_|  |_|\\___|_|  \\__, |\\___|   |_|\\___|\\__,_|_|  |___/             '
         '                          |___/                                             '
         '                                                                            '
         ------------------------------------------------------------------------------
         """

    print(header)

    parser = defaultParser()

    parser.add_argument("--silentMode",  action='store_true', dest="silentMode",    help="Remove as much as possible the print and the log/err files production")


    opt = parser.parse_args()
    print ("opt.pycfg            = ", opt.pycfg)
    loadDefaultOptions(parser, opt.pycfg)
    opt = parser.parse_args()

    print ("opt.tag              = ", opt.tag)
    print ("opt.variablesFile    = ", opt.variablesFile)
    print ("opt.cutsFile         = ", opt.cutsFile)
    print ("opt.samplesFile      = ", opt.samplesFile)
    print ("opt.structureFile    = ", opt.structureFile)
    print ("opt.nuisancesFile    = ", opt.nuisancesFile)
    print ("opt.foldersToMerge   = ", opt.foldersToMerge)
    print ("opt.inPath		 = ", opt.inPath)

    #
    # since the tricky part is the handling of the nuisances
    # there is the need to read the nuisances.py of each single "folder to merge"
    #
    # for the time being it assumes that the different files are named "nuisances.py"
    # alternatively it will need to read the configuration.py file for each folder
    # and extract the correct name of the "nuisances.py" file
    #

    foldersToMergeNuisancesFiles = {
        k : os.path.join(p["folder"], 'nuisances.py') for k, p in opt.foldersToMerge.items()
        }
    print ("foldersToMergeNuisancesFiles   = ", foldersToMergeNuisancesFiles)

    factory = MergerFactory()

    # ~~~~
    #
    # read list of samples
    #
    samples = {}
    if os.path.exists(opt.samplesFile) :
      handle = open(opt.samplesFile,'r')
      exec(handle.read())
      handle.close()
      # clean the dictionary to remove globals due to "exec" funcionality
      samples = {k: v for k, v in samples.items() if not (k.startswith('__') and k.endswith('__'))}

    # print ("samples = ", samples)

    #
    # read list of variables
    #
    variables = {}
    if os.path.exists(opt.variablesFile) :
      handle = open(opt.variablesFile,'r')
      exec(handle.read())
      handle.close()
      # clean the dictionary to remove globals due to "exec" funcionality
      variables = {k: v for k, v in variables.items() if not (k.startswith('__') and k.endswith('__'))}

    print ("variables = ", variables)


    #
    # read list of cuts
    #
    cuts = {}
    if os.path.exists(opt.cutsFile) :
      handle = open(opt.cutsFile,'r')
      exec(handle.read())
      handle.close()
      # clean the dictionary to remove globals due to "exec" funcionality
      cuts = {k: v for k, v in cuts.items() if not (k.startswith('__') and k.endswith('__'))}

    print ("cuts = ", cuts)


    #
    # read list of nuisances
    #
    nuisances = {}
    if os.path.exists(opt.nuisancesFile) :
      handle = open(opt.nuisancesFile,'r')
      exec(handle.read())
      handle.close()
      # clean the dictionary to remove globals due to "exec" funcionality
      nuisances = {k: v for k, v in nuisances.items() if not (k.startswith('__') and k.endswith('__'))}

    print ("nuisances = ", nuisances)


    factory.merge(
       opt.tag,
       variables,
       cuts,
       samples,
       nuisances,
       opt.foldersToMerge,
       foldersToMergeNuisancesFiles,
       opt.inPath,
       )


    print ("\n\n")
    print (" I'm done ... \n\n")


