from pipeline.models.base import get_session
from pipeline.models.brand_profile import BrandProfile
from pipeline.models.customer_profile import CustomerProfile
from pipeline.models.product_profile import ProductProfile


def build_brand_profile(project_id: int) -> BrandProfile:
    """通过 ProductProfile → BrandProfile 链路查找品牌画像。
    找不到时返回空 BrandProfile 对象（不写入数据库）。
    唯一合法路径：project → product_profile → brand_profile
    """
    session = get_session()
    try:
        product = session.query(ProductProfile).filter_by(project_id=project_id).first()
        if product and product.brand_profile_id:
            bp = session.get(BrandProfile, product.brand_profile_id)
            if bp:
                session.expunge(bp)
                return bp

        return BrandProfile()
    finally:
        session.close()


def get_brand_hierarchy(project_id: int) -> dict:
    """project → product_profile → brand_profile → customer_profile 链路查找，任一层级缺失时优雅降级"""
    session = get_session()
    try:
        result = {"customer": None, "brand": None, "product": None}

        product = session.query(ProductProfile).filter_by(project_id=project_id).first()
        if product:
            session.expunge(product)
            result["product"] = product

            if product.brand_profile_id:
                brand = session.get(BrandProfile, product.brand_profile_id)
                if brand:
                    session.expunge(brand)
                    result["brand"] = brand

                    if brand.customer_profile_id:
                        customer = session.get(
                            CustomerProfile, brand.customer_profile_id
                        )
                        if customer:
                            session.expunge(customer)
                            result["customer"] = customer

        return result
    finally:
        session.close()
