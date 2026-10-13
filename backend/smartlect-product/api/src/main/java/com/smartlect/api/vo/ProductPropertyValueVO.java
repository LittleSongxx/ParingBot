package com.smartlect.api.vo;

public class ProductPropertyValueVO implements java.io.Serializable {
    private static final long serialVersionUID = 1L;
    private String propertyValueId;

    private String propertyValue;

    private  String propertyCover;

    private String propertyGallery;

    private String propertyRemark;

    public String getPropertyValueId() {
        return propertyValueId;
    }

    public void setPropertyValueId(String propertyValueId) {
        this.propertyValueId = propertyValueId;
    }

    public String getPropertyValue() {
        return propertyValue;
    }

    public void setPropertyValue(String propertyValue) {
        this.propertyValue = propertyValue;
    }

    public String getPropertyCover() {
        return propertyCover;
    }

    public void setPropertyCover(String propertyCover) {
        this.propertyCover = propertyCover;
    }

    public String getPropertyGallery() {
        return propertyGallery;
    }

    public void setPropertyGallery(String propertyGallery) {
        this.propertyGallery = propertyGallery;
    }

    public String getPropertyRemark() {
        return propertyRemark;
    }

    public void setPropertyRemark(String propertyRemark) {
        this.propertyRemark = propertyRemark;
    }
}
