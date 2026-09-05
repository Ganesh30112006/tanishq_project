import { Router, type IRouter } from "express";
import healthRouter from "./health";
import careRouter from "./care";

const router: IRouter = Router();

router.use(healthRouter);
router.use(careRouter);

export default router;
