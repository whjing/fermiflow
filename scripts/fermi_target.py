import os
import gt_apps as my_apps
from LATSourceModel import SourceList
from GtApp import GtApp
import numpy as np
import subprocess
import logging
from glob import glob
from regions import Regions
import xml.etree.ElementTree as ET

import pyLikelihood
from BinnedAnalysis import BinnedAnalysis, BinnedObs
from UpperLimits import UpperLimits


# The command-line runner configures handlers, filename, and timestamps.
logger = logging.getLogger("FermiAnalysis")
print = logger.info


class FermiTarget:
    def __init__(
        self,
        name,
        c_ra="INDEF",
        c_dec="INDEF",
        rad="INDEF",
        tmin="INDEF",
        tmax="INDEF",
        emin="INDEF",
        emax="INDEF",
        zmax=90,
        evclass=128,
        evtype=3,
        dir_template=None,
        dir_rawdata=None,
        dir_products=None,
        file_catalog=None,
        file_diffuse=None,
        file_pointsrc=None,
        file_evtlist="binned_events.txt",
        irfs="P8R3_SOURCE_V3",
        path_ltcube=None,
        path_model_input=None,
        mapsize_deg=20.0,
        binsz=0.1,
    ):
        """
        初始化 Fermi 数据对象，集中管理所有的固有物理参数和输入输出文件命名
        """
        # set logger

        # --- 物理与观测参数 ---
        self.name = name
        self.ra = c_ra
        self.dec = c_dec
        self.rad = rad
        self.tmin = tmin
        self.tmax = tmax
        self.emin = emin
        self.emax = emax
        self.zmax = zmax
        self.evclass = evclass
        self.evtype = evtype

        #
        self.enumbins = round(10 * np.log10(emax / emin))
        print(f"Energy bins configured: {self.enumbins} (range: {self.emin}-{self.emax} MeV)")

        self.mapsize_deg = float(mapsize_deg)
        self.binsz = float(binsz)

        if self.mapsize_deg <= 0 or self.binsz <= 0:
            raise ValueError("mapsize_deg and binsz must be positive.")

        self.nxpix = int(round(self.mapsize_deg / self.binsz))
        self.nypix = self.nxpix

        if self.nxpix < 1:
            raise ValueError("Map dimensions must be at least one pixel.")

        # setup
        self.irfs = irfs  
        self.dir_template = dir_template
        self.dir_rawdata = dir_rawdata
        sc_files = glob(os.path.join(self.dir_rawdata, "*SC*.fits")) #传入飞船文件

        self.path_sc = sc_files[0]

        self.file_evtlist = file_evtlist
        self.path_evtlist = None

        # model file
        self.path_catalog = os.path.join(self.dir_template, file_catalog)
        self.path_diffuse = os.path.join(self.dir_template, file_diffuse)
        self.path_pointsrc = os.path.join(self.dir_template, file_pointsrc)

        # output file path
        self.dir_products = dir_products
        os.makedirs(self.dir_products, exist_ok=True)  # 确保输出目录存在

        self.path_filtered = os.path.join(
            self.dir_products, f"{self.name}_filtered.fits"
        )  # filtered event file path
        self.path_gti = os.path.join(
            self.dir_products, f"{self.name}_gti.fits"
        )  # gti file path
        self.path_cmap = os.path.join(
            self.dir_products, f"{self.name}_cmap.fits"
        )  # counts map file path
        self.path_ccube = os.path.join(
            self.dir_products, f"{self.name}_ccube.fits"
        )  # exposure cube file path
        if path_model_input is not None and os.path.exists(path_model_input):
            self.path_model_input = path_model_input
            print(f"[{self.name}] Using pre-existing model input {self.path_model_input}")
        else:
            self.path_model_input = os.path.join(
                self.dir_products, f"{self.name}_model_16yr.xml"
            )  # 4FGL XML 模型文件路径

        self.path_srcmaps = os.path.join(
            self.dir_products, f"{self.name}_srcmaps.fits"
        )  # source maps file path

        # Keep a configured ltcube in the project data directory.  When it
        # does not exist yet, gtltcube will create it at this exact path.
        if path_ltcube is not None:
            self.path_ltcube = os.path.abspath(os.path.expanduser(path_ltcube))
            if os.path.exists(self.path_ltcube):
                print(f"[{self.name}] Using pre-existing ltcube {self.path_ltcube}")
        else:
            self.path_ltcube = os.path.join(
                self.dir_products, f"{self.name}_ltcube.fits"
            )  # livetime cube file path

        os.makedirs(os.path.dirname(self.path_ltcube), exist_ok=True)

        # binned exposure map file path 
        self.path_bexpmap = os.path.join(self.dir_products, f"{self.name}_bexpmap.fits")

    def _call(self, tool_obj):
        """
        通用工具运行器：负责提取命令、执行、并【实时】把 C++ 输出抓进 Python 日志和终端
        """
        cmd = tool_obj.command()
        logger.info(f"[RUN] Executing command: {cmd}")

        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # 1 表示行缓冲，即遇到换行符就立刻推出来
        )

        for line in process.stdout:
            clean_line = line.strip()
            if clean_line:
                logger.info(f"{clean_line}")

        process.wait()

        # check if the command was successful
        if process.returncode != 0:
            logger.error(f"Command failed with return code: {process.returncode}")
            raise RuntimeError(
                "Fermi tool execution failed. Please check the log file for details."
            )

    def exam_rawdata(self):
        """Check the raw data directory structure and file naming conventions."""
        print(f"[{self.name}] [RUN] Checking raw data directory structure and file naming conventions...")
        if not os.path.isdir(self.dir_rawdata):
            raise FileNotFoundError(
                f"Raw data directory does not exist: {self.dir_rawdata}"
            )

        # Check if the required files exist
        required_files = [
            self.path_sc,
            self.path_catalog,
            self.path_diffuse,
            self.path_pointsrc,
        ]
        for f in required_files:
            if not os.path.exists(f):
                raise FileNotFoundError(f"Missing required input file: {f}")

        print(f"[DONE] Raw data directory structure and file naming conventions check passed.\n")

    def export_evtlist(self, dir_rawdata=None):
        """生成包含所有原始事件文件的列表 (txt)"""
        self.path_evtlist = os.path.join(self.dir_rawdata, self.file_evtlist)

        os.system(f"ls -1 {self.dir_rawdata}/*PH*.fits > {self.path_evtlist}")

        print(f"[DONE] Event list file generated: {self.path_evtlist}\n")

        return self.path_evtlist

    def run_gtselect(self, startfrom = "evtlist"):
        if self.path_evtlist and startfrom == "evtlist":
            logger.info(f"Using event list file as input for gtselect: {self.path_evtlist}")
            my_apps.filter["infile"] = self.path_evtlist
        elif self.path_gti and startfrom == "gti":
            logger.info(f"Using GTI file as input for gtselect: {self.path_gti}")
            my_apps.filter["infile"] = self.path_gti
        else:
            raise ValueError("No input file available for gtselect.")
        
        """执行 gtselect (通常不接收额外参数，全靠自身属性)"""
        print(f"[RUN] Starting gtselect...")
        my_apps.filter["evclass"] = self.evclass
        my_apps.filter["evtype"] = self.evtype
        
        my_apps.filter["outfile"] = self.path_filtered
        my_apps.filter["ra"] = self.ra
        my_apps.filter["dec"] = self.dec
        my_apps.filter["rad"] = self.rad
        my_apps.filter["tmin"] = self.tmin
        my_apps.filter["tmax"] = self.tmax
        my_apps.filter["emin"] = self.emin
        my_apps.filter["emax"] = self.emax
        my_apps.filter["zmax"] = self.zmax
        self._call(my_apps.filter)
        print(f"[DONE] gtselect finished.\n")

    def run_gtmktime(self, filter_exp="(DATA_QUAL>0)&&(LAT_CONFIG==1)", roicut="no"):
        """Execute gtmktime"""
        print(f"[RUN] Starting gtmktime...")
        my_apps.maketime["scfile"] = self.path_sc
        my_apps.maketime["filter"] = filter_exp
        my_apps.maketime["roicut"] = roicut
        my_apps.maketime["evfile"] = self.path_filtered
        my_apps.maketime["outfile"] = self.path_gti
        self._call(my_apps.maketime)
        print(f"[DONE] gtmktime finished.\n")

    def run_gtbin_cmap(
        self, proj="AIT", coordsys="CEL", axisrot=0.0):
        """执行 gtbin 生成 2D 计数图 (像素大小、投影方式作为可变参数)"""
        print(f"[RUN] Starting gtbin (count map generation)...")
        my_apps.evtbin["algorithm"] = "CMAP"
        my_apps.evtbin["evfile"] = self.path_gti
        my_apps.evtbin["outfile"] = self.path_cmap
        my_apps.evtbin["scfile"] = "None"
        my_apps.evtbin["nxpix"] = self.nxpix
        my_apps.evtbin["nypix"] = self.nypix
        my_apps.evtbin["binsz"] = self.binsz
        my_apps.evtbin["coordsys"] = coordsys
        my_apps.evtbin["xref"] = self.ra
        my_apps.evtbin["yref"] = self.dec
        my_apps.evtbin["axisrot"] = axisrot
        my_apps.evtbin["proj"] = proj
        my_apps.evtbin["enumbins"] = self.enumbins
        self._call(my_apps.evtbin)

    def run_gtbin_ccube(
        self, proj="AIT", coordsys="CEL", ebinalg="LOG"
    ):
        """执行 gtexpcube 生成曝光/活时立方体"""
        print("[RUN] Starting gtbin (counts cube generation)...")
        my_apps.evtbin["algorithm"] = "CCUBE"
        my_apps.evtbin["evfile"] = self.path_gti
        my_apps.evtbin["outfile"] = self.path_ccube
        my_apps.evtbin["scfile"] = "None"
        my_apps.evtbin["nxpix"] = self.nxpix
        my_apps.evtbin["nypix"] = self.nypix
        my_apps.evtbin["binsz"] = self.binsz
        my_apps.evtbin["coordsys"] = coordsys
        my_apps.evtbin["xref"] = self.ra
        my_apps.evtbin["yref"] = self.dec
        my_apps.evtbin["proj"] = proj
        my_apps.evtbin["ebinalg"] = ebinalg
        my_apps.evtbin["emin"] = self.emin
        my_apps.evtbin["emax"] = self.emax
        my_apps.evtbin["enumbins"] = self.enumbins
        self._call(my_apps.evtbin)
        print("[DONE] gtbin counts cube generation finished.\n")

    def download_models(
        self,
        url="https://fermi.gsfc.nasa.gov/ssc/data/access/lat/fl16y/gll_psc_16yr_v38.xml",
    ):
        """使用 wget 下载背景模型或星表"""
        print(f"[RUN] Downloading model file...")
        os.system(f"wget -c {url} -P {self.dir_rawdata}")
        print(f"[DONE] Model file download finished.\n")

    def convert_ds9_to_carta(self, file_ds9, file_carta):
        """示例：将 DS9 区域文件转换为 CARTA 格式（如果需要）"""
    
        regs = Regions.read(file_ds9, format="ds9")
        regs.write(file_carta, format="ds9", overwrite=True)

        print(f"[DONE] Converted DS9 region file '{file_ds9}' to CARTA format '{file_carta}'.")

    def run_make4FGLxml(
        self,
        DR=4,
        free_radius=5,
        max_free_radius=5,
        sigma_to_free=5,
        variable_free=True,
    ):

        print(f"[RUN] Generating 4FGL XML model...")

        # 替换掉了硬编码的 PG1553，全部使用对象的属性
        source_list = SourceList(
            catalog_file=self.path_catalog,
            ROI=self.path_gti,
            output_name=self.path_model_input,  # 生成的 XML 模型文件路径
            DR=DR,
        )
        # --- 核心修改：安全地拆分路径和文件名 ---
        model_dir = os.path.dirname(self.path_model_input)
        model_name = os.path.basename(self.path_model_input)

        # 安全拼接 DS9 和 CARTA 的文件名
        ds9_name = f"ROI_{model_name.replace('.xml', '.reg')}"
        carta_name = f"ROI_{model_name.replace('.xml', '_carta.reg')}"

        # 重新和目录组合成绝对安全的完整路径
        file_ds9 = os.path.join(model_dir, ds9_name)
        file_carta = os.path.join(model_dir, carta_name)

        source_list.make_model(
            galactic_file=self.path_diffuse,
            isotropic_file=self.path_pointsrc,
            free_radius=free_radius,
            max_free_radius=max_free_radius,
            sigma_to_free=sigma_to_free,
            variable_free=variable_free,
            region_file=file_ds9,
            galactic_index_free=False,  # new
        )

        self.convert_ds9_to_carta(file_ds9=file_ds9, file_carta=file_carta)
        print(f"[{self.name}] [DONE] 4FGL XML model generated: {self.path_model_input}\n")

    def check_free_params(self, max_free=70):
        """
        检查输入 XML 模型中的自由参数数量，如果超过 max_free 则抛出异常暂停流水线。
        """
        xml_file = self.path_model_input
        print(f"[RUN] Checking free parameters in {xml_file}...")

        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
        except Exception as e:
            raise RuntimeError(f"Failed to parse XML file {xml_file}: {e}")

        free_count = 0
        # 遍历所有的 parameter 标签
        for param in root.iter("parameter"):
            if param.get("free") == "1":
                free_count += 1

        print(f"[{self.name}] Total free parameters found: {free_count}")

        if free_count > max_free:
            raise RuntimeError(
                f"Number of free parameters ({free_count}) exceeds the safe limit of {max_free}. Pipeline halted to prevent MINUIT crash."
            )

        print(f"[DONE] Parameter check passed. Safe to run gtlike.\n")

    def run_gtltcube(self, zmax=90, dcostheta=0.025, binsz=1):
        """
        6. compute livetimes and exposure
        """
        my_apps.expCube["evfile"] = self.path_gti
        my_apps.expCube["scfile"] = self.path_sc
        my_apps.expCube["outfile"] = self.path_ltcube

        my_apps.expCube["zmax"] = zmax
        my_apps.expCube["dcostheta"] = dcostheta
        my_apps.expCube["binsz"] = binsz
        self._call(my_apps.expCube)
        print(f"[DONE] gtltcube finished. Saved as: {self.path_ltcube}\n")

    def run_gtexpcube2(
        self,
        cmap="none",
        nxpix=3600,
        nypix=1800,
        binsz=0.1,
        axisrot=0,
        proj="AIT",
        coordsys="CEL",
    ):
        """
        7. compute exposure map: for all sky
        can also be excuted with a counts map
        P8R3_SOURCE_V3： response function
        """
        expCube2 = GtApp("gtexpcube2", "Likelihood")
        expCube2["infile"] = self.path_ltcube
        expCube2["cmap"] = self.path_ccube
        expCube2["outfile"] = self.path_bexpmap
        expCube2["irfs"] = self.irfs
        expCube2["evtype"] = self.evtype
        expCube2["nxpix"] = nxpix
        expCube2["nypix"] = nypix
        expCube2["binsz"] = binsz
        expCube2["coordsys"] = coordsys
        expCube2["xref"] = self.ra
        expCube2["yref"] = self.dec
        expCube2["axisrot"] = axisrot
        expCube2["proj"] = proj
        expCube2["emin"] = self.emin
        expCube2["emax"] = self.emax
        expCube2["enumbins"] = self.enumbins
        self._call(expCube2)

    def run_gtsrcmaps(self, input_model, output_srcmaps=None):
        """
        Generate source maps using an explicitly specified XML model.
        """

        if not os.path.exists(input_model):
            raise FileNotFoundError(f"Input XML model does not exist: {input_model}")

        if output_srcmaps is None:
            output_srcmaps = self.path_srcmaps

        logger.info("[RUN] Starting gtsrcmaps...")
        logger.info(f"Input model : {input_model}")
        logger.info(f"Output maps : {output_srcmaps}")

        my_apps.srcMaps["expcube"] = self.path_ltcube
        my_apps.srcMaps["cmap"] = self.path_ccube
        my_apps.srcMaps["srcmdl"] = input_model
        my_apps.srcMaps["outfile"] = output_srcmaps
        my_apps.srcMaps["bexpmap"] = self.path_bexpmap
        my_apps.srcMaps["irfs"] = self.irfs

        self._call(my_apps.srcMaps)

        logger.info(f"[DONE] gtsrcmaps finished: {output_srcmaps}")

        return output_srcmaps

    def run_gtlike(
        self,
        input_model,
        output_model,
        optimizer="DRMNFB",
        srcmaps=None,
        statistic="BINNED",
    ):
        """
        Run gtlike with explicitly specified input/output XML models.
        """

        if not os.path.exists(input_model):
            raise FileNotFoundError(f"Input XML model does not exist: {input_model}")

        if srcmaps is None:
            srcmaps = self.path_srcmaps

        if not os.path.exists(srcmaps):
            raise FileNotFoundError(f"Source maps do not exist: {srcmaps}")

        output_base = os.path.splitext(output_model)[0]
        results_file = output_base + "_results.dat"
        specfile = output_base + "_spec.fits"

        logger.info("[RUN] Starting gtlike...")
        logger.info(f"Optimizer    : {optimizer}")
        logger.info(f"Input model  : {input_model}")
        logger.info(f"Output model : {output_model}")
        logger.info(f"Source maps  : {srcmaps}")

        gtlike = GtApp("gtlike", "Likelihood")

        gtlike["sfile"] = output_model
        gtlike["statistic"] = statistic
        gtlike["expcube"] = self.path_ltcube
        gtlike["srcmdl"] = input_model
        gtlike["cmap"] = srcmaps
        gtlike["bexpmap"] = self.path_bexpmap
        gtlike["irfs"] = self.irfs
        gtlike["optimizer"] = optimizer
        gtlike["results"] = results_file
        gtlike["specfile"] = specfile

        self._call(gtlike)

        if not os.path.exists(output_model):
            raise RuntimeError(
                f"gtlike finished but output model was not created: " f"{output_model}")

        logger.info(f"[DONE] gtlike ({optimizer}) finished: {output_model}")

        return output_model

    def print_fit_summary(self, model_file, srcmaps, source_name="kes27"):
        """Print final likelihood, TS, fluxes, and spectral parameters."""

        obs = BinnedObs(
            srcMaps=srcmaps,
            expCube=self.path_ltcube,
            binnedExpMap=self.path_bexpmap,
            irfs=self.irfs,
        )

        like = BinnedAnalysis(obs, model_file, optimizer="NEWMINUIT")

        if source_name not in like.sourceNames():
            raise ValueError(f"Source not found in model: {source_name}")

        fit_object = pyLikelihood.NewMinuit(like.logLike)
        like.fit(verbosity=0, covar=True, optObject=fit_object)

        ret_code = fit_object.getRetCode()
        if ret_code != 0:
            logger.warning(f"NEWMINUIT return code: {ret_code}")

        neg_log_likelihood = -like.logLike.value()
        photon_flux = like.flux(source_name, self.emin, self.emax)
        photon_flux_error = like.fluxError(source_name, self.emin, self.emax)

        energy_flux = like.energyFlux(source_name, self.emin, self.emax)
        energy_flux_error = like.energyFluxError(source_name, self.emin, self.emax)

        ts_value = like.Ts(source_name, reoptimize=True, verbosity=0)

        upper_limit_text = ""
        if ts_value < 5:
            try:
                upper_limits = UpperLimits(like)
                photon_flux_ul, _ = upper_limits[source_name].compute(
                    emin=self.emin,
                    emax=self.emax,
                    delta=1.355,
                )
                upper_limit_text = (
                    f"\n95% photon-flux UL ({self.emin:g}-{self.emax:g} MeV): "
                    f"{photon_flux_ul:.4e} ph cm^-2 s^-1\n"
                )
            except Exception as error:
                logger.warning(
                    f"Could not calculate 95% upper limit for {source_name}: {error}"
                )

        logger.info(
            f"-log(Likelihood): {neg_log_likelihood:.3f}\n"
            f"TS({source_name}): {ts_value:.3f}\n"
            f"Photon flux ({self.emin:g}-{self.emax:g} MeV): "
            f"({photon_flux:.4e} ± {photon_flux_error:.4e}) ph cm^-2 s^-1\n"
            f"Energy flux ({self.emin:g}-{self.emax:g} MeV): "
            f"({energy_flux * 1.602176634e-6:.4e} ± "
            f"{energy_flux_error * 1.602176634e-6:.4e}) erg cm^-2 s^-1\n"
            f"Spectral parameters:\n{like.model[source_name]}"
            f"{upper_limit_text}"
        )

        return ts_value

    def run_gtsrcmap_gtlike2(self, input_model, source_name="kes27"):
        """
        Complete fitting workflow:

        input model
            -> gtsrcmaps
            -> gtlike (DRMNFB)
            -> gtlike (MINUIT)
        """

        # Define output filenames
        srcmaps = input_model.replace("_input.xml", "_srcmaps.fits")
        drmnfb_model = input_model.replace("_input.xml", "_drmnfb.xml")
        minuit_model = input_model.replace("_input.xml", "_minuit.xml")

        # Step 1: Generate source maps
        generated_srcmaps = self.run_gtsrcmaps(
            input_model=input_model,
            output_srcmaps=srcmaps,
        )

        # Step 2: First likelihood fit with DRMNFB
        fitted_drmnfb = self.run_gtlike(
            input_model=input_model,
            output_model=drmnfb_model,
            optimizer="DRMNFB",
            srcmaps=generated_srcmaps,
        )

        # Step 3: Second likelihood fit with MINUIT
        fitted_minuit = self.run_gtlike(
            input_model=fitted_drmnfb,
            output_model=minuit_model,
            optimizer="MINUIT",
            srcmaps=generated_srcmaps,
        )

        self.print_fit_summary(
            model_file=fitted_minuit,
            srcmaps=generated_srcmaps,
            source_name=source_name,
        )

        logger.info("Model fitting workflow completed.")
        logger.info(f"Source maps : {generated_srcmaps}")
        logger.info(f"Final model : {fitted_minuit}")

        return fitted_minuit

    def run_gttsmap(
        self,
        statistic="BINNED",
        xsize=2,
        ysize=2,
        binsz=0.05,
        proj="AIT",
        coordsys="CEL",
        optimizer="MINUIT",
        path_model=None,
        path_tsmap=None,
        chatter=2,
    ):
        if not os.path.exists(path_model):
            raise FileNotFoundError(f"TS-map input model does not exist: {path_model}")
        logger.info("[RUN] Starting gttsmap...")
        logger.info(f"Input model : {path_model}")

        if path_tsmap is None:
            path_tsmap = path_model.replace(".xml", ".fits")
            logger.info(f"Output map  : {path_tsmap}")

        nxpix = int(xsize / binsz)
        nypix = int(ysize / binsz)
        logger.info(f"Generating {nxpix} * {nypix} image with pixel size of {binsz}")

        # 配置参数字典
        my_apps.TsMap["statistic"] = statistic
        my_apps.TsMap["scfile"] = self.path_sc  # spacecraft 文件
        my_apps.TsMap["evfile"] = self.path_gti  # 过滤好的事件文件
        my_apps.TsMap["cmap"] = self.path_ccube  # 3D Counts Cube
        my_apps.TsMap["bexpmap"] = self.path_bexpmap  # 曝光图
        my_apps.TsMap["expcube"] = self.path_ltcube  # 活时立方体
        my_apps.TsMap["srcmdl"] = path_model
        my_apps.TsMap["irfs"] = self.irfs
        my_apps.TsMap["optimizer"] = optimizer
        my_apps.TsMap["outfile"] = path_tsmap

        # 空间T格M置
        my_apps.TsMap["nxpix"] = nxpix
        my_apps.TsMap["nypix"] = nypix
        my_apps.TsMap["binsz"] = binsz
        my_apps.TsMap["coordsys"] = coordsys
        my_apps.TsMap["xref"] = self.ra
        my_apps.TsMap["yref"] = self.dec
        my_apps.TsMap["proj"] = proj
        my_apps.TsMap["chatter"] = (chatter)

        # 调用我们之前写好的拦截器，实时输出日志和进度！
        self._call(my_apps.TsMap)

        logger.info(f"[DONE] gttsmap finished. TS map saved as: {my_apps.TsMap['outfile']}\n")


__all__ = ["FermiTarget", "logger"]
